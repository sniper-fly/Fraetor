from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from src.dictation.application.app_state import AppState
from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.application.stt_event_relay import SttEventRelay
from src.dictation.domain.models import RecordingSession
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster


def _make_app_state() -> AppState:
    app_state = AppState(broadcaster=SSEBroadcaster())
    app_state.current_session = RecordingSession(
        id="session-1", segments=[], started_at=datetime.now(tz=UTC)
    )
    return app_state


class TestWatch:
    async def test_interim_broadcasts_sse(self) -> None:
        """interim → SSE("interim") → ブラウザ (グレー)"""
        app_state = _make_app_state()
        accumulator = SegmentAccumulator(app_state.broadcaster)
        relay = SttEventRelay(app_state, accumulator)
        sub = app_state.broadcaster.subscribe()
        event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue)

        event_queue.put_nowait({"type": "interim", "text": "中間結果"})
        await asyncio.sleep(0.05)

        msg = sub.get_nowait()
        assert msg["event"] == "interim"
        data = json.loads(msg["data"])
        assert data["text"] == "中間結果"
        assert data["session_id"] == "session-1"

        await relay.stop()

    async def test_recognized_creates_segment_and_broadcasts(self) -> None:
        """recognized → SSE → ブラウザ (緑)"""
        app_state = _make_app_state()
        accumulator = SegmentAccumulator(app_state.broadcaster)
        relay = SttEventRelay(app_state, accumulator)
        sub = app_state.broadcaster.subscribe()
        event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue)

        event_queue.put_nowait({"type": "recognized", "text": "認識結果"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 1
        seg = session.segments[0]
        assert seg.id == 0
        assert seg.text == "認識結果"

        msg = sub.get_nowait()
        assert msg["event"] == "recognized"
        data = json.loads(msg["data"])
        assert data["segment_id"] == 0
        assert data["text"] == "認識結果"
        assert data["session_id"] == "session-1"

        await relay.stop()

    async def test_segment_ids_increment(self) -> None:
        app_state = _make_app_state()
        accumulator = SegmentAccumulator(app_state.broadcaster)
        relay = SttEventRelay(app_state, accumulator)
        event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue)

        event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        event_queue.put_nowait({"type": "recognized", "text": "2つ目"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 2
        assert session.segments[0].id == 0
        assert session.segments[1].id == 1

        await relay.stop()

    async def test_new_session_restarts_segment_ids(self) -> None:
        """新規セッションはsegmentsが空のため採番も0から始まる"""
        app_state = _make_app_state()
        accumulator = SegmentAccumulator(app_state.broadcaster)
        relay = SttEventRelay(app_state, accumulator)
        event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue)
        event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        await asyncio.sleep(0.05)
        await relay.stop()

        app_state.current_session = RecordingSession(
            id="session-2",
            segments=[],
            started_at=datetime.now(tz=UTC),
        )
        event_queue2: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue2)
        event_queue2.put_nowait({"type": "recognized", "text": "2セッション目"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert session.segments[0].id == 0

        await relay.stop()

    async def test_stop_cancels_watch_without_draining(self) -> None:
        """stop()は監視ループを止めるだけで、キューの残りは処理しない"""
        app_state = _make_app_state()
        accumulator = SegmentAccumulator(app_state.broadcaster)
        relay = SttEventRelay(app_state, accumulator)
        event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        relay.start(event_queue)

        await relay.stop()
        event_queue.put_nowait({"type": "recognized", "text": "ドレインされない"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 0
