from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

from src.dictation.application.segment_silence_monitor import SegmentSilenceMonitor


class TestSilenceDetection:
    async def test_fires_once_after_silence_threshold(self) -> None:
        """発話終了から segment_silence_sec 経過で1回呼ばれる。"""
        on_silence = AsyncMock()
        last_speech = time.monotonic()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=0.1,
            last_speech_time_fn=lambda: last_speech,
            on_silence=on_silence,
        )

        monitor.start()
        await asyncio.sleep(0.15)
        await monitor.stop()

        on_silence.assert_awaited_once()

    async def test_does_not_fire_while_speech_continues(self) -> None:
        """発話が続く間 (last_speech_time が更新され続ける間) は呼ばれない。"""
        on_silence = AsyncMock()
        last_speech = time.monotonic()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=0.3,
            last_speech_time_fn=lambda: last_speech,
            on_silence=on_silence,
        )
        monitor.start()

        for _ in range(3):
            await asyncio.sleep(0.1)
            last_speech = time.monotonic()

        on_silence.assert_not_awaited()

        await monitor.stop()

    async def test_fires_repeatedly_while_silence_persists(self) -> None:
        """無音が閾値の2倍以上続くと複数回呼ばれる。

        重複呼び出しは仕様 (送信すべきものがあるかの判定は flush 側の
        no-op ガードに委ねる)。抑制されていないことを明示的に検証する。
        """
        on_silence = AsyncMock()
        last_speech = time.monotonic()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=0.1,
            last_speech_time_fn=lambda: last_speech,
            on_silence=on_silence,
        )

        monitor.start()
        await asyncio.sleep(0.35)
        await monitor.stop()

        assert on_silence.await_count >= 2

    async def test_resumes_correct_timing_after_speech_resumes(self) -> None:
        """発火後に発話が再開すると、その終了から改めて閾値分待つ。

        発火直後の固定スリープ中に発話が始まった場合、目覚めた時点で残り時間の
        再計算に戻れないと、新しい発話の途中で区切ってしまう。
        """
        on_silence = AsyncMock()
        last_speech = time.monotonic()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=0.2,
            last_speech_time_fn=lambda: last_speech,
            on_silence=on_silence,
        )

        monitor.start()
        await asyncio.sleep(0.25)
        assert on_silence.await_count == 1

        # 発火直後の固定スリープ中に発話が再開した状況を作る
        await asyncio.sleep(0.1)
        last_speech = time.monotonic()
        await asyncio.sleep(0.15)

        assert on_silence.await_count == 1, "発話終了から0.2秒経つ前は発火しない"

        await asyncio.sleep(0.1)
        await monitor.stop()

        assert on_silence.await_count == 2


class TestStop:
    async def test_stop_cancels_watch_task(self) -> None:
        on_silence = AsyncMock()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=10,
            last_speech_time_fn=time.monotonic,
            on_silence=on_silence,
        )
        monitor.start()

        await monitor.stop()

        assert monitor._task is None
        on_silence.assert_not_awaited()

    async def test_stop_prevents_further_calls(self) -> None:
        """停止後は閾値を過ぎても呼ばれない (タスクリークがない)。"""
        on_silence = AsyncMock()
        last_speech = time.monotonic()
        monitor = SegmentSilenceMonitor(
            segment_silence_sec=0.1,
            last_speech_time_fn=lambda: last_speech,
            on_silence=on_silence,
        )

        monitor.start()
        await monitor.stop()
        await asyncio.sleep(0.2)

        on_silence.assert_not_awaited()
