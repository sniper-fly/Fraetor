from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dictation.domain.models import RecordingSession
    from src.dictation.domain.ports import EventBroadcasterPort


class AppState:
    def __init__(self, broadcaster: EventBroadcasterPort) -> None:
        self.broadcaster: EventBroadcasterPort = broadcaster
        self.current_session: RecordingSession | None = None
        self.recording: bool = False
