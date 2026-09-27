from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.transcript_history.domain.models import FinalizedSession


class PendingSessionStore:
    """文字起こし完了済み・未確定(finalize-session未実行)のセッションを保持する。

    旧`dictation.application.AppState.pending_sessions`の責務を移設したもの。
    """

    def __init__(self) -> None:
        self._sessions: list[FinalizedSession] = []

    def add(self, session: FinalizedSession) -> None:
        self._sessions.append(session)

    def pop(self, session_id: str) -> FinalizedSession | None:
        for i, session in enumerate(self._sessions):
            if session.id == session_id:
                return self._sessions.pop(i)
        return None
