from __future__ import annotations

from datetime import UTC, datetime

from src.dictation.application.app_state import AppState
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster
from src.transcript_history.domain.models import FinalizedSession


def _make_finalized_session(session_id: str) -> FinalizedSession:
    return FinalizedSession(
        id=session_id,
        segments=[],
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        timed_out=False,
    )


class TestAppState:
    def test_initial_state(self) -> None:
        broadcaster = SSEBroadcaster()
        app_state = AppState(broadcaster=broadcaster)

        assert app_state.broadcaster is broadcaster
        assert app_state.current_session is None
        assert app_state.recording is False
        assert app_state.pending_sessions == []


class TestPendingSessions:
    def test_add_pending_session_appends_in_fifo_order(self) -> None:
        app_state = AppState(broadcaster=SSEBroadcaster())
        first = _make_finalized_session("first")
        second = _make_finalized_session("second")

        app_state.add_pending_session(first)
        app_state.add_pending_session(second)

        assert app_state.pending_sessions == [first, second]

    def test_pop_pending_session_removes_only_matching_id(self) -> None:
        app_state = AppState(broadcaster=SSEBroadcaster())
        first = _make_finalized_session("first")
        second = _make_finalized_session("second")
        app_state.add_pending_session(first)
        app_state.add_pending_session(second)

        popped = app_state.pop_pending_session("first")

        assert popped == first
        assert app_state.pending_sessions == [second]

    def test_pop_pending_session_with_unknown_id_returns_none(self) -> None:
        app_state = AppState(broadcaster=SSEBroadcaster())
        app_state.add_pending_session(_make_finalized_session("first"))

        popped = app_state.pop_pending_session("unknown")

        assert popped is None
        assert len(app_state.pending_sessions) == 1
