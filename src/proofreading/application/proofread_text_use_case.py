from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.proofreading.domain.ports import ProofreadingPort
    from src.shared.config.ports import SettingsRepositoryPort

logger = logging.getLogger(__name__)


class ProofreadTextUseCase:
    """テキスト校正ユースケース。校正器未設定/失敗/タイムアウト時は元テキストを返す。"""

    def __init__(
        self,
        proofreader: ProofreadingPort | None,
        *,
        settings_repository: SettingsRepositoryPort,
    ) -> None:
        self._proofreader = proofreader
        self._settings_repository = settings_repository

    async def execute(self, text: str) -> tuple[str, bool]:
        """校正済みテキストと、校正が行われたかを返す。"""
        if self._proofreader is None:
            return text, False
        # タイムアウトは校正の実行ごとに読む (設定画面からの変更を次回の
        # 校正から反映するため)。
        timeout_sec = self._settings_repository.get().proofread_timeout_sec
        try:
            result = await asyncio.wait_for(
                self._proofreader.proofread(text), timeout=timeout_sec
            )
        except Exception:
            logger.exception("Proofreading failed")
            return text, False
        return result, True
