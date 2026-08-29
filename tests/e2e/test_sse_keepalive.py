"""SSE keepalive の実HTTPストリーミング経由の動作を検証するE2Eテスト。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from tests.e2e.conftest import AudioServerHandle

_KEEPALIVE_WAIT_SEC = 15.0


class TestSseKeepalive:
    async def test_keepalive_interval_keeps_connection_alive(
        self, fraetor_audio_server_handle: AudioServerHandle
    ) -> None:
        """異常系: keepalive間隔を短縮した状態でも接続が正しく維持される"""
        base_url = fraetor_audio_server_handle.start(
            "05_toggle_recording.wav",
            settings_overrides={"sse_keepalive_sec": 1},
        )

        async with (
            httpx.AsyncClient(base_url=base_url, timeout=None) as client,
            client.stream("GET", "/events") as sse_response,
        ):

            async def collect_two_keepalives() -> int:
                count = 0
                async for event in iter_sse_events(sse_response):
                    if event["event"] == "keepalive":
                        count += 1
                        if count >= 2:
                            return count
                return count

            count = await asyncio.wait_for(
                collect_two_keepalives(), timeout=_KEEPALIVE_WAIT_SEC
            )

        assert count >= 2
