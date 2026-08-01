"""実プロセスのライフサイクル (shutdown 系) を検証するE2Eテスト。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from tests.e2e.conftest import AudioServerHandle

_SHUTDOWN_WAIT_SEC = 15.0
_SESSION_END_WAIT_SEC = 30.0


class TestShutdown:
    async def test_shutdown_terminates_the_real_process(
        self, fraetor_audio_server_handle: AudioServerHandle
    ) -> None:
        """正常系: /api/shutdown実行後、実プロセスが実際に終了コードで終了する"""
        base_url = fraetor_audio_server_handle.start("05_toggle_recording.wav")

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.post("/api/shutdown")
        assert response.status_code == 200

        process = fraetor_audio_server_handle.process
        assert process is not None
        await asyncio.to_thread(process.wait, timeout=_SHUTDOWN_WAIT_SEC)
        assert process.returncode is not None

    async def test_shutdown_during_recording_stops_session_before_exit(
        self, fraetor_audio_server_handle: AudioServerHandle
    ) -> None:
        """正常系: 録音中のshutdownはstop_session完了(履歴保存)後にプロセスが終了する"""
        base_url = fraetor_audio_server_handle.start("01_normal_speech.wav")

        async with (
            httpx.AsyncClient(base_url=base_url, timeout=None) as client,
            client.stream("GET", "/events") as sse_response,
        ):
            await client.post("/api/toggle-recording")

            events: list[dict[str, str]] = []

            async def collect_until_shutdown() -> None:
                async for event in iter_sse_events(sse_response):
                    events.append(event)
                    if event["event"] == "shutdown":
                        return

            await client.post("/api/shutdown")
            await asyncio.wait_for(
                collect_until_shutdown(), timeout=_SESSION_END_WAIT_SEC
            )

        event_names = [e["event"] for e in events]
        # session_end (履歴保存の前提) が shutdown より先に発火していること
        assert "session_end" in event_names
        assert event_names.index("session_end") < event_names.index("shutdown")
