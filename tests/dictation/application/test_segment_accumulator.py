from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.domain.models import RecordingSession
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster


def _make_session() -> RecordingSession:
    return RecordingSession(
        id="session-1", segments=[], started_at=datetime.now(tz=UTC)
    )


class TestHandleEvent:
    async def test_interim_broadcasts_without_touching_session(self) -> None:
        broadcaster = SSEBroadcaster()
        sub = broadcaster.subscribe()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()

        await accumulator.handle_event(session, {"type": "interim", "text": "中間"})

        assert session.segments == []
        msg = sub.get_nowait()
        assert msg["event"] == "interim"
        data = json.loads(msg["data"])
        assert data["text"] == "中間"
        assert data["session_id"] == "session-1"

    async def test_recognized_appends_segment_and_broadcasts(self) -> None:
        broadcaster = SSEBroadcaster()
        sub = broadcaster.subscribe()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()

        await accumulator.handle_event(
            session, {"type": "recognized", "text": "認識結果"}
        )

        assert len(session.segments) == 1
        assert session.segments[0].id == 0
        assert session.segments[0].text == "認識結果"
        msg = sub.get_nowait()
        assert msg["event"] == "recognized"
        data = json.loads(msg["data"])
        assert data["segment_id"] == 0
        assert data["text"] == "認識結果"
        assert data["session_id"] == "session-1"

    async def test_segment_id_derived_from_existing_segment_count(self) -> None:
        """セグメントIDは session.segments の長さから算出される (状態を持たない)"""
        broadcaster = SSEBroadcaster()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()

        await accumulator.handle_event(session, {"type": "recognized", "text": "1つ目"})
        await accumulator.handle_event(session, {"type": "recognized", "text": "2つ目"})

        assert session.segments[0].id == 0
        assert session.segments[1].id == 1

    async def test_recognized_with_no_session_is_ignored(self) -> None:
        broadcaster = SSEBroadcaster()
        accumulator = SegmentAccumulator(broadcaster)

        await accumulator.handle_event(
            None, {"type": "recognized", "text": "無視される"}
        )

    async def test_recognized_passes_through_text_transform(self) -> None:
        """recognizedイベントのテキストはSegment生成前にtransformされる。"""
        broadcaster = SSEBroadcaster()
        sub = broadcaster.subscribe()
        text_transform = AsyncMock()
        text_transform.transform = AsyncMock(return_value="変換後")
        accumulator = SegmentAccumulator(broadcaster, text_transform=text_transform)
        session = _make_session()

        await accumulator.handle_event(
            session, {"type": "recognized", "text": "変換前"}
        )

        text_transform.transform.assert_awaited_once_with("session-1", "変換前")
        assert session.segments[0].text == "変換後"
        msg = sub.get_nowait()
        data = json.loads(msg["data"])
        assert data["text"] == "変換後"

    async def test_interim_does_not_invoke_text_transform(self) -> None:
        broadcaster = SSEBroadcaster()
        text_transform = AsyncMock()
        text_transform.transform = AsyncMock(return_value="変換後")
        accumulator = SegmentAccumulator(broadcaster, text_transform=text_transform)
        session = _make_session()

        await accumulator.handle_event(session, {"type": "interim", "text": "中間"})

        text_transform.transform.assert_not_awaited()

    async def test_none_text_transform_leaves_existing_behavior_unaffected(
        self,
    ) -> None:
        broadcaster = SSEBroadcaster()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()

        await accumulator.handle_event(
            session, {"type": "recognized", "text": "そのまま"}
        )

        assert session.segments[0].text == "そのまま"


class TestDrain:
    async def test_drains_all_queued_events_into_session(self) -> None:
        broadcaster = SSEBroadcaster()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        queue.put_nowait({"type": "recognized", "text": "ドレイン"})
        queue.put_nowait({"type": "interim", "text": "中間は無視"})

        await accumulator.drain(session, queue)

        assert queue.empty()
        assert len(session.segments) == 1
        assert session.segments[0].text == "ドレイン"

    async def test_drain_on_empty_queue_is_noop(self) -> None:
        broadcaster = SSEBroadcaster()
        accumulator = SegmentAccumulator(broadcaster)
        session = _make_session()
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        await accumulator.drain(session, queue)

        assert session.segments == []
