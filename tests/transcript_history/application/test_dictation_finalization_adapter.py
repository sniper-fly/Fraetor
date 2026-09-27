from __future__ import annotations

from datetime import UTC, datetime

from dictation.domain.models import RecordingSession, Segment

from src.transcript_history.application.dictation_finalization_adapter import (
    DictationSessionFinalizationAdapter,
)
from src.transcript_history.application.pending_session_store import (
    PendingSessionStore,
)


def _make_recording_session() -> RecordingSession:
    return RecordingSession(
        id="session-1",
        segments=[Segment(id=0, text="認識結果")],
        started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
    )


class TestOnSessionFinalized:
    async def test_converts_and_adds_to_pending_store(self) -> None:
        store = PendingSessionStore()
        adapter = DictationSessionFinalizationAdapter(store)
        session = _make_recording_session()
        ended_at = datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC)

        await adapter.on_session_finalized(session, ended_at=ended_at, timed_out=False)

        finalized = store.pop("session-1")
        assert finalized is not None
        assert finalized.full_text == "認識結果"
        assert finalized.ended_at == ended_at
        assert finalized.timed_out is False

    async def test_propagates_timed_out_flag(self) -> None:
        store = PendingSessionStore()
        adapter = DictationSessionFinalizationAdapter(store)
        session = _make_recording_session()

        await adapter.on_session_finalized(
            session, ended_at=datetime.now(tz=UTC), timed_out=True
        )

        finalized = store.pop("session-1")
        assert finalized is not None
        assert finalized.timed_out is True
