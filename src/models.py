from datetime import datetime

from pydantic import BaseModel


class Segment(BaseModel):
    id: int
    text: str


class Session(BaseModel):
    id: str
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime | None = None
    timed_out: bool = False

    @property
    def full_text(self) -> str:
        return "".join(seg.text for seg in self.segments if seg.text)
