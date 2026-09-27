from __future__ import annotations

from typing import TYPE_CHECKING

from dictation.domain.ports import SessionFinalizationHookPort

from src.transcript_history.domain.models import FinalizedSession

if TYPE_CHECKING:
    from datetime import datetime

    from dictation.domain.models import RecordingSession

    from src.transcript_history.application.pending_session_store import (
        PendingSessionStore,
    )


class DictationSessionFinalizationAdapter(SessionFinalizationHookPort):
    """dictationの`SessionFinalizationHookPort`を実装し、transcript_historyへ橋渡しする唯一の接続点。

    dictationモジュールはこのクラスを`SessionFinalizationHookPort`としてのみ
    知り、transcript_history側の具象には依存しない(境界づけられたコンテキスト
    間の逆依存を避ける)。
    """

    def __init__(self, pending_store: PendingSessionStore) -> None:
        self._pending_store = pending_store

    async def on_session_finalized(
        self, session: RecordingSession, *, ended_at: datetime, timed_out: bool
    ) -> None:
        finalized = FinalizedSession.from_recording(
            session, ended_at=ended_at, timed_out=timed_out
        )
        self._pending_store.add(finalized)
