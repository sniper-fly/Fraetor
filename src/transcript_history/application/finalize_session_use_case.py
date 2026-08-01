from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.transcript_history.domain.models import FinalizedSession
    from src.transcript_history.domain.ports import ClipboardPort, HistoryRepositoryPort

logger = logging.getLogger(__name__)


class FinalizeSessionUseCase:
    """確定済みセッションをクリップボードにコピーし、履歴に保存する。"""

    def __init__(
        self, clipboard: ClipboardPort, history_repository: HistoryRepositoryPort
    ) -> None:
        self._clipboard = clipboard
        self._history_repository = history_repository

    async def execute(self, session: FinalizedSession, *, text: str) -> None:
        try:
            await self._clipboard.copy(text)
        except Exception:
            logger.exception("Failed to copy text to clipboard")
        try:
            self._history_repository.save(session, text_override=text)
        except Exception:
            logger.exception("Failed to save session history")
