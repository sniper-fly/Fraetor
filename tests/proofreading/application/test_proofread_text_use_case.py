from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.proofreading.application.proofread_text_use_case import ProofreadTextUseCase


class TestExecute:
    async def test_returns_proofread_text_when_successful(self) -> None:
        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.return_value = "校正済みテキスト"
        use_case = ProofreadTextUseCase(mock_proofreader, timeout_sec=15)

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "校正済みテキスト"
        assert proofread is True
        mock_proofreader.proofread.assert_called_once_with("元のテキスト")

    async def test_returns_original_when_proofreader_none(self) -> None:
        use_case = ProofreadTextUseCase(None, timeout_sec=15)

        text, proofread = await use_case.execute("テスト")

        assert text == "テスト"
        assert proofread is False

    async def test_returns_original_on_error(self) -> None:
        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.side_effect = RuntimeError("API error")
        use_case = ProofreadTextUseCase(mock_proofreader, timeout_sec=15)

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "元のテキスト"
        assert proofread is False

    async def test_returns_original_on_timeout(self) -> None:
        async def slow_proofread(text: str) -> str:
            await asyncio.sleep(10)
            return "遅い結果" + text

        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.side_effect = slow_proofread
        use_case = ProofreadTextUseCase(mock_proofreader, timeout_sec=0.05)

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "元のテキスト"
        assert proofread is False
