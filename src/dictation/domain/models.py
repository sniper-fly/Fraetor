from datetime import datetime

from pydantic import BaseModel


class Segment(BaseModel):
    id: int
    text: str


class RecordingSession(BaseModel):
    """録音中のmutableな実行時状態。"""

    id: str
    segments: list[Segment] = []
    started_at: datetime

    @property
    def full_text(self) -> str:
        return "".join(seg.text for seg in self.segments if seg.text)
