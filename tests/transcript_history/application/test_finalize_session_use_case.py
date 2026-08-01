from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.dictation.domain.models import Segment
from src.transcript_history.application.finalize_session_use_case import (
    FinalizeSessionUseCase,
)
from src.transcript_history.domain.models import FinalizedSession


def _make_session() -> FinalizedSession:
    return FinalizedSession(
        id="test-session-id",
        segments=[Segment(id=0, text="校正済み。")],
        started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC),
        timed_out=False,
    )


class TestExecute:
    async def test_copies_and_saves(self) -> None:
        mock_clipboard = AsyncMock()
        mock_history_repository = MagicMock()
        use_case = FinalizeSessionUseCase(mock_clipboard, mock_history_repository)
        session = _make_session()

        await use_case.execute(session, text="edited text")

        mock_clipboard.copy.assert_called_once_with("edited text")
        mock_history_repository.save.assert_called_once_with(
            session, text_override="edited text"
        )

    async def test_continues_saving_when_clipboard_fails(self) -> None:
        mock_clipboard = AsyncMock()
        mock_clipboard.copy.side_effect = RuntimeError("clipboard error")
        mock_history_repository = MagicMock()
        use_case = FinalizeSessionUseCase(mock_clipboard, mock_history_repository)
        session = _make_session()

        await use_case.execute(session, text="edited text")

        mock_history_repository.save.assert_called_once_with(
            session, text_override="edited text"
        )

    async def test_swallows_history_save_failure(self) -> None:
        mock_clipboard = AsyncMock()
        mock_history_repository = MagicMock()
        mock_history_repository.save.side_effect = RuntimeError("disk error")
        use_case = FinalizeSessionUseCase(mock_clipboard, mock_history_repository)
        session = _make_session()

        await use_case.execute(session, text="edited text")

        mock_clipboard.copy.assert_called_once_with("edited text")
