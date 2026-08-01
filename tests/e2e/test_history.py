"""JSONL履歴ファイルへの実ファイルシステム書き込みを検証するE2Eテスト。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from collections.abc import Callable

_SESSION_END_WAIT_SEC = 30.0


async def _run_session_and_finalize(base_url: str) -> None:
    """録音開始→session_end待ち→finalize-sessionまで実行する。"""
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

    async with httpx.AsyncClient(base_url=base_url) as client:
        await client.post("/api/finalize-session", json={"text": "確認用テキスト"})


class TestHistoryFile:
    async def test_consecutive_sessions_appended_in_order(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 複数セッションを連続実行し、JSONLに正しい順序で追記される"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")

        await _run_session_and_finalize(base_url)
        await _run_session_and_finalize(base_url)

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get("/api/history")

        sessions = response.json()
        assert len(sessions) == 2
        # /api/history は新しい順に返すため、ended_at で古い→新しいに並び直す
        ended_ats = [s["ended_at"] for s in sessions]
        assert ended_ats == sorted(ended_ats, reverse=True)

    async def test_delete_nonexistent_session_returns_404(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """異常系: 存在しないセッションIDの削除リクエストで404"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.delete("/api/history/nonexistent-session-id")

        assert response.status_code == 404
