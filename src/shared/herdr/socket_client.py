from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

from src.shared.herdr.ports import HerdrClientPort, HerdrSessionInfo

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SEC = 2.0


def _resolve_socket_path() -> Path:
    if env_path := os.environ.get("HERDR_SOCKET_PATH"):
        return Path(env_path)
    if session_name := os.environ.get("HERDR_SESSION"):
        return (
            Path.home() / ".config" / "herdr" / "sessions" / session_name / "herdr.sock"
        )
    return Path.home() / ".config" / "herdr" / "herdr.sock"


class HerdrSocketClient(HerdrClientPort):
    def __init__(self, socket_path: Path | None = None) -> None:
        self._socket_path = (
            socket_path if socket_path is not None else _resolve_socket_path()
        )

    async def _call(
        self, method: str, params: dict[str, Any] | None = None
    ) -> Any | None:
        if not self._socket_path.exists():
            return None
        request = {
            "id": f"req_{uuid.uuid4().hex}",
            "method": method,
            "params": params or {},
        }
        try:
            reader, writer = await asyncio.open_unix_connection(str(self._socket_path))
        except OSError as e:
            logger.warning("Herdr socket接続に失敗しました: %s", e)
            return None
        try:
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(
                reader.readline(), timeout=_CONNECT_TIMEOUT_SEC
            )
        except (OSError, TimeoutError) as e:
            logger.warning("Herdr socket通信に失敗しました (method=%s): %s", method, e)
            return None
        finally:
            writer.close()
        try:
            response = json.loads(line)
        except json.JSONDecodeError as e:
            logger.warning("Herdrからの応答をパースできませんでした: %s", e)
            return None
        return response.get("result")

    async def get_focused_pane_id(self) -> str | None:
        result = await self._call("session.snapshot")
        if not result:
            return None
        pane_id = result.get("focused_pane_id")
        return pane_id if isinstance(pane_id, str) else None

    async def list_sessions(self) -> list[HerdrSessionInfo]:
        result = await self._call("pane.list")
        if not result:
            return []
        panes = result.get("panes")
        if not isinstance(panes, list):
            return []
        sessions = []
        for pane in panes:
            pane_id = pane.get("pane_id") or pane.get("id")
            if not pane_id:
                continue
            label = pane.get("label") or pane.get("title") or pane_id
            sessions.append(HerdrSessionInfo(pane_id=pane_id, label=label))
        return sessions

    async def send_text(self, pane_id: str, text: str) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                "herdr", "agent", "prompt", pane_id, text
            )
            returncode = await process.wait()
        except OSError as e:
            logger.warning("herdr agent prompt の実行に失敗しました: %s", e)
            return False
        if returncode != 0:
            logger.warning(
                "herdr agent prompt が非0で終了しました: returncode=%d", returncode
            )
            return False
        return True
