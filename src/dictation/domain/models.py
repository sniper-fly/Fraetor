import asyncio
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.dictation.domain.ports import SttEnginePort


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


class TranscriptionJob(BaseModel):
    """文字起こし待ちの1セッション分のジョブ。

    `SttEnginePort` (ABCインスタンス) と `asyncio.Queue` をフィールドに
    持つため `arbitrary_types_allowed` が必要。ロジックは持たせず、
    `TranscriptionQueue` に引き渡すデータの入れ物に徹する。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    session: RecordingSession
    stt_client: SttEnginePort
    event_queue: asyncio.Queue[dict[str, str]]
    timed_out: bool
