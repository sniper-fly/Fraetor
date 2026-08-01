from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

from src.dictation.application.session_timeout_monitor import SessionTimeoutMonitor


class TestAutoTimeout:
    async def test_auto_stops_after_max_duration(self) -> None:
        """最大セッション時間経過 → 超過時はon_timeoutが呼ばれる"""
        on_timeout = AsyncMock()
        monitor = SessionTimeoutMonitor(
            max_duration_sec=0.1,
            silence_timeout_sec=10,
            last_speech_time_fn=time.monotonic,
            on_timeout=on_timeout,
        )

        monitor.start()
        await asyncio.sleep(0.2)

        on_timeout.assert_called_once()

    async def test_auto_stops_after_silence_timeout(self) -> None:
        """発話なしのまま silence_timeout_sec 経過 → on_timeoutが呼ばれる"""
        on_timeout = AsyncMock()
        session_start = time.monotonic()
        monitor = SessionTimeoutMonitor(
            max_duration_sec=10,
            silence_timeout_sec=0.1,
            last_speech_time_fn=lambda: session_start,
            on_timeout=on_timeout,
        )

        monitor.start()
        await asyncio.sleep(0.2)

        on_timeout.assert_called_once()

    async def test_speech_detection_resets_silence_timer(self) -> None:
        """last_speech_time_fnが更新され続ける間は無音タイムアウトが発動しない"""
        on_timeout = AsyncMock()
        last_speech_time = time.monotonic()

        def last_speech_time_fn() -> float:
            return last_speech_time

        monitor = SessionTimeoutMonitor(
            max_duration_sec=10,
            silence_timeout_sec=0.3,
            last_speech_time_fn=last_speech_time_fn,
            on_timeout=on_timeout,
        )
        monitor.start()

        for _ in range(3):
            await asyncio.sleep(0.1)
            last_speech_time = time.monotonic()

        on_timeout.assert_not_called()

        await monitor.stop()

    async def test_max_duration_stops_despite_speech(self) -> None:
        """発話が継続していても最大セッション時間で停止する"""
        on_timeout = AsyncMock()
        monitor = SessionTimeoutMonitor(
            max_duration_sec=0.1,
            silence_timeout_sec=10,
            last_speech_time_fn=time.monotonic,
            on_timeout=on_timeout,
        )

        monitor.start()
        await asyncio.sleep(0.2)

        on_timeout.assert_called_once()


class TestStop:
    async def test_stop_cancels_watch_task(self) -> None:
        on_timeout = AsyncMock()
        monitor = SessionTimeoutMonitor(
            max_duration_sec=10,
            silence_timeout_sec=10,
            last_speech_time_fn=time.monotonic,
            on_timeout=on_timeout,
        )
        monitor.start()

        await monitor.stop()

        assert monitor._task is None
        on_timeout.assert_not_called()
