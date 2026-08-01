from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dictation.domain.models import RecordingSession
    from src.dictation.domain.ports import EventBroadcasterPort
    from src.transcript_history.domain.models import FinalizedSession


class AppState:
    def __init__(self, broadcaster: EventBroadcasterPort) -> None:
        self.stt_event_queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        self.broadcaster: EventBroadcasterPort = broadcaster
        self.current_session: RecordingSession | None = None
        self.recording: bool = False
        self.pending_session: FinalizedSession | None = None
