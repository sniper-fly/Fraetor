from __future__ import annotations

from datetime import UTC, datetime

from src.dictation.domain.models import RecordingSession, Segment
from src.transcript_history.domain.models import FinalizedSession


class TestFinalizedSession:
    def test_from_recording_copies_fields(self) -> None:
        recording = RecordingSession(
            id="s1",
            segments=[Segment(id=0, text="テスト")],
            started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
        )
        ended_at = datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC)

        finalized = FinalizedSession.from_recording(
            recording, ended_at=ended_at, timed_out=True
        )

        assert finalized.id == "s1"
        assert finalized.segments == [Segment(id=0, text="テスト")]
        assert finalized.started_at == recording.started_at
        assert finalized.ended_at == ended_at
        assert finalized.timed_out is True

    def test_full_text_assembled_from_segments(self) -> None:
        finalized = FinalizedSession(
            id="s1",
            segments=[Segment(id=0, text="A"), Segment(id=1, text="B")],
            started_at=datetime.now(tz=UTC),
            ended_at=datetime.now(tz=UTC),
            timed_out=False,
        )

        assert finalized.full_text == "AB"
