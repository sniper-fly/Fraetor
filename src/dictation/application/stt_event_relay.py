from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from src.dictation.domain.models import Segment

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState


class SttEventRelay:
    """STTイベントキューを監視し、セグメント作成+SSEブロードキャストを行う。

    監視ループ (`start`) とドレイン処理 (`stop_and_drain`) の両方が
    `_handle_event` を共有し、旧実装にあった処理ロジックの重複を解消する。
    """

    def __init__(self, app_state: AppState) -> None:
        self._app_state = app_state
        self._task: asyncio.Task[None] | None = None
        self._next_segment_id: int = 0

    def reset(self) -> None:
        self._next_segment_id = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._watch())

    async def stop_and_drain(self) -> None:
        """監視ループを止め、キューに残ったイベントを処理する。"""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

        queue = self._app_state.stt_event_queue
        while not queue.empty():
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self._handle_event(event)

    async def _watch(self) -> None:
        try:
            while True:
                event = await self._app_state.stt_event_queue.get()
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass

    async def _handle_event(self, event: dict[str, str]) -> None:
        if event["type"] == "interim":
            await self._app_state.broadcaster.broadcast(
                "interim", {"text": event["text"]}
            )
        elif event["type"] == "recognized":
            segment = self._add_segment(event["text"])
            await self._app_state.broadcaster.broadcast(
                "recognized",
                {"segment_id": segment.id, "text": segment.text},
            )

    def _add_segment(self, text: str) -> Segment:
        segment = Segment(id=self._next_segment_id, text=text)
        self._next_segment_id += 1
        if self._app_state.current_session:
            self._app_state.current_session.segments.append(segment)
        return segment
