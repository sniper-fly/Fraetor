from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime

from src.dictation.application.app_state import AppState
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
        relay = SttEventRelay(app_state)
        sub = app_state.broadcaster.subscribe()
        relay.start()

        app_state.stt_event_queue.put_nowait({"type": "interim", "text": "中間結果"})
        await asyncio.sleep(0.05)

        msg = sub.get_nowait()
        assert msg["event"] == "interim"
        assert json.loads(msg["data"])["text"] == "中間結果"

        await relay.stop_and_drain()

    async def test_recognized_creates_segment_and_broadcasts(self) -> None:
        """recognized → SSE → ブラウザ (緑)"""
        app_state = _make_app_state()
        relay = SttEventRelay(app_state)
        sub = app_state.broadcaster.subscribe()
        relay.start()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "認識結果"})
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

        await relay.stop_and_drain()

    async def test_segment_ids_increment(self) -> None:
        app_state = _make_app_state()
        relay = SttEventRelay(app_state)
        relay.start()

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "2つ目"})
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 2
        assert session.segments[0].id == 0
        assert session.segments[1].id == 1

        await relay.stop_and_drain()

    async def test_reset_restarts_segment_ids(self) -> None:
        app_state = _make_app_state()
        relay = SttEventRelay(app_state)
        relay.start()
        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "1つ目"})
        await asyncio.sleep(0.05)
        await relay.stop_and_drain()

        relay.reset()
        app_state.current_session = RecordingSession(
            id="session-2",
            segments=[],
            started_at=datetime.now(tz=UTC),
        )
        relay.start()
        app_state.stt_event_queue.put_nowait(
            {"type": "recognized", "text": "2セッション目"}
        )
        await asyncio.sleep(0.05)

        session = app_state.current_session
        assert session is not None
        assert session.segments[0].id == 0

        await relay.stop_and_drain()


class TestStopAndDrain:
    async def test_drains_recognized_events_after_task_cancelled(self) -> None:
        """停止時にキューに残ったrecognizedイベントもセグメントに反映される。"""
        app_state = _make_app_state()
        relay = SttEventRelay(app_state)
        relay.start()

        assert relay._task is not None
        relay._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await relay._task
        relay._task = None

        app_state.stt_event_queue.put_nowait({"type": "recognized", "text": "ドレイン"})
        app_state.stt_event_queue.put_nowait({"type": "interim", "text": "中間は無視"})

        await relay.stop_and_drain()

        session = app_state.current_session
        assert session is not None
        assert len(session.segments) == 1
        assert session.segments[0].text == "ドレイン"
