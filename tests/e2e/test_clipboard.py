"""`finalize-session` 実行後、実OSクリップボードに反映されるかを検証するE2Eテスト。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx
import pyperclip

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from collections.abc import Callable

_SESSION_END_WAIT_SEC = 30.0


async def _run_session_until_end(base_url: str) -> None:
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=None) as client,
        client.stream("GET", "/events") as sse_response,
    ):
        await client.post("/api/toggle-recording")

        async def wait_for_session_end() -> None:
            async for event in iter_sse_events(sse_response):
                if event["event"] == "session_end":
                    return

        await asyncio.wait_for(wait_for_session_end(), timeout=_SESSION_END_WAIT_SEC)


class TestClipboard:
    async def test_finalize_session_copies_text_to_real_clipboard(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: finalize-session後、実クリップボードから期待テキストが読み出せる"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")
        await _run_session_until_end(base_url)

        expected_text = "上書きされたテキスト"
        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post(
                "/api/finalize-session", json={"text": expected_text}
            )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
        pasted = pyperclip.paste()  # type: ignore[no-untyped-call]
        assert pasted == expected_text
