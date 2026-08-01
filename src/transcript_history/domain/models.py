from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.dictation.domain.models import RecordingSession, Segment


class FinalizedSession(BaseModel):
    """録音停止後の保存確定レコード。immutable。"""

    model_config = ConfigDict(frozen=True)

    id: str
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime
    timed_out: bool

    @property
    def full_text(self) -> str:
        return "".join(seg.text for seg in self.segments if seg.text)

    @classmethod
    def from_recording(
        cls, session: RecordingSession, *, ended_at: datetime, timed_out: bool
    ) -> "FinalizedSession":
        return cls(
            id=session.id,
            segments=session.segments,
            started_at=session.started_at,
            ended_at=ended_at,
            timed_out=timed_out,
        )
