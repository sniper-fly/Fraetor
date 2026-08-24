from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from src.shared.herdr.socket_client import HerdrSocketClient

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def short_tmp_dir() -> Iterator[Path]:
    # tmp_path (pytest既定) はネストが深く AF_UNIX のパス長上限を超えるため、
    # ソケットファイル用には /tmp 直下の短いディレクトリを別途使う。
    path = Path(tempfile.mkdtemp())
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


async def _serve_one_response(
    socket_path: Path, response: dict[str, object]
) -> asyncio.AbstractServer:
    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readline()
        writer.write((json.dumps(response) + "\n").encode())
        await writer.drain()
        writer.close()

    return await asyncio.start_unix_server(handle, path=str(socket_path))


class TestGetFocusedPane:
    async def test_parses_focused_pane_from_snapshot(self, short_tmp_dir: Path) -> None:
        """実際のsession.snapshotレスポンスはfocused_pane_id/panesを
        result.snapshot配下にネストする (result直下ではない)。"""
        socket_path = short_tmp_dir / "herdr.sock"
        server = await _serve_one_response(
            socket_path,
            {
                "result": {
                    "type": "session_snapshot",
                    "snapshot": {
                        "focused_pane_id": "w1:p1",
                        "panes": [
                            {
                                "pane_id": "w1:p1",
                                "terminal_title_stripped": "Claude Code",
                            },
                            {"pane_id": "w1:p2", "terminal_title_stripped": "shell"},
                        ],
                    },
                }
            },
        )
        client = HerdrSocketClient(socket_path=socket_path)

        pane = await client.get_focused_pane()

        assert pane is not None
        assert (pane.pane_id, pane.label) == ("w1:p1", "Claude Code")
        server.close()
        await server.wait_closed()

    async def test_returns_none_when_focused_pane_not_in_panes(
        self, short_tmp_dir: Path
    ) -> None:
        socket_path = short_tmp_dir / "herdr.sock"
        server = await _serve_one_response(
            socket_path,
            {
                "result": {
                    "snapshot": {
                        "focused_pane_id": "w1:p1",
                        "panes": [],
                    }
                }
            },
        )
        client = HerdrSocketClient(socket_path=socket_path)

        assert await client.get_focused_pane() is None
        server.close()
        await server.wait_closed()

    async def test_returns_none_when_socket_missing(self, tmp_path: Path) -> None:
        client = HerdrSocketClient(socket_path=tmp_path / "missing.sock")

        assert await client.get_focused_pane() is None


class TestListSessions:
    async def test_converts_pane_list_response(self, short_tmp_dir: Path) -> None:
        socket_path = short_tmp_dir / "herdr.sock"
        server = await _serve_one_response(
            socket_path,
            {
                "result": {
                    "panes": [
                        {"pane_id": "w1:p1", "terminal_title_stripped": "claude-code"},
                        {"pane_id": "w1:p2", "terminal_title_stripped": "shell"},
                    ]
                }
            },
        )
        client = HerdrSocketClient(socket_path=socket_path)

        sessions = await client.list_sessions()

        assert [(s.pane_id, s.label) for s in sessions] == [
            ("w1:p1", "claude-code"),
            ("w1:p2", "shell"),
        ]
        server.close()
        await server.wait_closed()

    async def test_falls_back_to_terminal_title_when_stripped_is_missing(
        self, short_tmp_dir: Path
    ) -> None:
        """terminal_title_strippedが無い場合はterminal_titleへ、
        それも無い場合はpane_idそのものへフォールバックする。"""
        socket_path = short_tmp_dir / "herdr.sock"
        server = await _serve_one_response(
            socket_path,
            {
                "result": {
                    "panes": [
                        {"pane_id": "w1:p1", "terminal_title": "✳ Claude Code"},
                        {"pane_id": "w1:p2"},
                    ]
                }
            },
        )
        client = HerdrSocketClient(socket_path=socket_path)

        sessions = await client.list_sessions()

        assert [(s.pane_id, s.label) for s in sessions] == [
            ("w1:p1", "✳ Claude Code"),
            ("w1:p2", "w1:p2"),
        ]
        server.close()
        await server.wait_closed()

    async def test_returns_empty_list_when_socket_missing(self, tmp_path: Path) -> None:
        client = HerdrSocketClient(socket_path=tmp_path / "missing.sock")

        assert await client.list_sessions() == []


class TestSendText:
    async def test_returns_true_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeProcess:
            async def wait(self) -> int:
                return 0

        async def fake_create_subprocess_exec(
            *_args: object, **_kwargs: object
        ) -> FakeProcess:
            return FakeProcess()

        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", fake_create_subprocess_exec
        )
        client = HerdrSocketClient(socket_path=None)

        assert await client.send_text("w1:p1", "hello") is True

    async def test_returns_false_on_nonzero_returncode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeProcess:
            async def wait(self) -> int:
                return 1

        async def fake_create_subprocess_exec(
            *_args: object, **_kwargs: object
        ) -> FakeProcess:
            return FakeProcess()

        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", fake_create_subprocess_exec
        )
        client = HerdrSocketClient(socket_path=None)

        assert await client.send_text("w1:p1", "hello") is False

    async def test_returns_false_when_herdr_binary_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_create_subprocess_exec(
            *_args: object, **_kwargs: object
        ) -> None:
            raise FileNotFoundError

        monkeypatch.setattr(
            asyncio, "create_subprocess_exec", fake_create_subprocess_exec
        )
        client = HerdrSocketClient(socket_path=None)

        assert await client.send_text("w1:p1", "hello") is False
