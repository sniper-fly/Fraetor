from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.dictation.domain.models import RecordingSession
    from src.dictation.domain.ports import EventBroadcasterPort
    from src.transcript_history.domain.models import FinalizedSession


class AppState:
    def __init__(self, broadcaster: EventBroadcasterPort) -> None:
        self.broadcaster: EventBroadcasterPort = broadcaster
        self.current_session: RecordingSession | None = None
        self.recording: bool = False
        self.pending_sessions: list[FinalizedSession] = []

    def add_pending_session(self, session: FinalizedSession) -> None:
        self.pending_sessions.append(session)

    def pop_pending_session(self, session_id: str) -> FinalizedSession | None:
        for i, session in enumerate(self.pending_sessions):
            if session.id == session_id:
                return self.pending_sessions.pop(i)
        return None
