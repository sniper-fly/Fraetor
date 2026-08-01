from __future__ import annotations

from datetime import UTC, datetime

from src.dictation.domain.models import RecordingSession, Segment


class TestRecordingSession:
    def test_full_text_assembled_from_segments(self) -> None:
        session = RecordingSession(
            id="s1",
            segments=[
                Segment(id=0, text="こんにちは。"),
                Segment(id=1, text="お元気ですか。"),
            ],
            started_at=datetime.now(tz=UTC),
        )

        assert session.full_text == "こんにちは。お元気ですか。"

    def test_full_text_empty_when_no_segments(self) -> None:
        session = RecordingSession(
            id="s1", segments=[], started_at=datetime.now(tz=UTC)
        )

        assert session.full_text == ""

    def test_full_text_skips_empty_segment_text(self) -> None:
        session = RecordingSession(
            id="s1",
            segments=[Segment(id=0, text=""), Segment(id=1, text="テスト")],
            started_at=datetime.now(tz=UTC),
        )

        assert session.full_text == "テスト"
