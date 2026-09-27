from __future__ import annotations

from datetime import UTC, datetime

from src.transcript_history.application.pending_session_store import (
    PendingSessionStore,
)
from src.transcript_history.domain.models import FinalizedSession


def _make_finalized_session(session_id: str) -> FinalizedSession:
    return FinalizedSession(
        id=session_id,
        segments=[],
        started_at=datetime.now(tz=UTC),
        ended_at=datetime.now(tz=UTC),
        timed_out=False,
    )


class TestPendingSessionStore:
    def test_add_appends_in_fifo_order(self) -> None:
        store = PendingSessionStore()
        first = _make_finalized_session("first")
        second = _make_finalized_session("second")

        store.add(first)
        store.add(second)

        assert store.pop("first") == first
        assert store.pop("second") == second

    def test_pop_removes_only_matching_id(self) -> None:
        store = PendingSessionStore()
        first = _make_finalized_session("first")
        second = _make_finalized_session("second")
        store.add(first)
        store.add(second)

        popped = store.pop("first")

        assert popped == first
        assert store.pop("first") is None
        assert store.pop("second") == second

    def test_pop_with_unknown_id_returns_none(self) -> None:
        store = PendingSessionStore()
        store.add(_make_finalized_session("first"))

        popped = store.pop("unknown")

        assert popped is None
