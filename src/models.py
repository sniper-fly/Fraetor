from datetime import datetime
from typing import Literal

from pydantic import BaseModel

SegmentStatus = Literal["interim", "correcting", "corrected"]


class Segment(BaseModel):
    id: int
    status: SegmentStatus
    raw_text: str
    corrected_text: str = ""


class Session(BaseModel):
    id: str
    segments: list[Segment]
    started_at: datetime
    ended_at: datetime | None = None
    correction_enabled: bool
    timed_out: bool = False

    @property
    def full_text(self) -> str:
        parts: list[str] = []
        for seg in self.segments:
            text = seg.corrected_text if seg.corrected_text else seg.raw_text
            if text:
                parts.append(text)
        return "".join(parts)
