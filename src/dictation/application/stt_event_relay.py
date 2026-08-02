from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.segment_accumulator import SegmentAccumulator


class SttEventRelay:
    """録音中のSTTイベントキューを監視し、リアルタイムにSSE配信する。

    停止後の残イベント処理 (drain) は `TranscriptionQueue` が
    `SegmentAccumulator.drain` を直接呼んで行う。セッションごとに独立した
    `event_queue` を `start()` の引数として都度受け取る。
    """

    def __init__(self, app_state: AppState, accumulator: SegmentAccumulator) -> None:
        self._app_state = app_state
        self._accumulator = accumulator
        self._task: asyncio.Task[None] | None = None

    def start(self, event_queue: asyncio.Queue[dict[str, str]]) -> None:
        self._task = asyncio.create_task(self._watch(event_queue))

    async def stop(self) -> None:
        """監視ループを止める (drainは行わない)。"""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _watch(self, event_queue: asyncio.Queue[dict[str, str]]) -> None:
        try:
            while True:
                event = await event_queue.get()
                await self._accumulator.handle_event(
                    self._app_state.current_session, event
                )
        except asyncio.CancelledError:
            pass
