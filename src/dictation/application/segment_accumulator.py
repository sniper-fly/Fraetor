from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.dictation.domain.models import Segment

if TYPE_CHECKING:
    from src.dictation.domain.models import RecordingSession
    from src.dictation.domain.ports import (
        EventBroadcasterPort,
        RecognizedTextTransformPort,
    )


class SegmentAccumulator:
    """STTイベントをセグメントに変換し、セッションへの追記とSSE配信を行う。

    セグメントIDは `session.segments` の長さから算出するため状態を持たない。
    録音中のリアルタイム監視 (`SttEventRelay`) と、停止後の直列処理
    (`TranscriptionQueue`) の双方から共通に呼び出せる。
    """

    def __init__(
        self,
        broadcaster: EventBroadcasterPort,
        text_transform: RecognizedTextTransformPort | None = None,
    ) -> None:
        self._broadcaster = broadcaster
        self._text_transform = text_transform

    async def handle_event(
        self, session: RecordingSession | None, event: dict[str, str]
    ) -> None:
        if event["type"] == "interim":
            session_id = session.id if session is not None else None
            await self._broadcaster.broadcast(
                "interim", {"session_id": session_id, "text": event["text"]}
            )
        elif event["type"] == "recognized":
            if session is None:
                return
            text = event["text"]
            if self._text_transform is not None:
                text = await self._text_transform.transform(session.id, text)
            segment = Segment(id=len(session.segments), text=text)
            session.segments.append(segment)
            await self._broadcaster.broadcast(
                "recognized",
                {
                    "session_id": session.id,
                    "segment_id": segment.id,
                    "text": segment.text,
                },
            )

    async def drain(
        self,
        session: RecordingSession | None,
        queue: asyncio.Queue[dict[str, str]],
    ) -> None:
        """キューに残ったイベントをすべて処理する。"""
        while not queue.empty():
            try:
                event = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self.handle_event(session, event)
