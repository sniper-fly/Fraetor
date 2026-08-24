from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.proofreading.application.proofread_text_use_case import ProofreadTextUseCase
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository


class TestExecute:
    async def test_returns_proofread_text_when_successful(self) -> None:
        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.return_value = "校正済みテキスト"
        use_case = ProofreadTextUseCase(
            mock_proofreader, settings_repository=InMemorySettingsRepository()
        )

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "校正済みテキスト"
        assert proofread is True
        mock_proofreader.proofread.assert_called_once_with("元のテキスト")

    async def test_returns_original_when_proofreader_none(self) -> None:
        use_case = ProofreadTextUseCase(
            None, settings_repository=InMemorySettingsRepository()
        )

        text, proofread = await use_case.execute("テスト")

        assert text == "テスト"
        assert proofread is False

    async def test_returns_original_on_error(self) -> None:
        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.side_effect = RuntimeError("API error")
        use_case = ProofreadTextUseCase(
            mock_proofreader, settings_repository=InMemorySettingsRepository()
        )

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "元のテキスト"
        assert proofread is False

    async def test_returns_original_on_timeout(self) -> None:
        async def slow_proofread(text: str) -> str:
            await asyncio.sleep(10)
            return "遅い結果" + text

        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.side_effect = slow_proofread
        use_case = ProofreadTextUseCase(
            mock_proofreader,
            settings_repository=InMemorySettingsRepository(
                DynamicSettings(proofread_timeout_sec=0.05)
            ),
        )

        text, proofread = await use_case.execute("元のテキスト")

        assert text == "元のテキスト"
        assert proofread is False


class TestDynamicTimeout:
    async def test_next_execution_uses_updated_timeout(self) -> None:
        """`update()` した値は次の `execute()` から反映される。

        所要時間の変わらない同一の校正器に対し、タイムアウトを縮めた/
        伸ばしただけで成否が反転することで、値が実行のたびに読み直されて
        いることを示す (ctor 時点で固定されていれば反転しない)。
        """

        async def slow_proofread(text: str) -> str:
            await asyncio.sleep(0.05)
            return "校正済み:" + text

        mock_proofreader = AsyncMock()
        mock_proofreader.proofread.side_effect = slow_proofread
        repo = InMemorySettingsRepository(DynamicSettings(proofread_timeout_sec=0.01))
        use_case = ProofreadTextUseCase(mock_proofreader, settings_repository=repo)

        assert await use_case.execute("A") == ("A", False)

        repo.update(DynamicSettings(proofread_timeout_sec=0.3))

        assert await use_case.execute("B") == ("校正済み:B", True)
