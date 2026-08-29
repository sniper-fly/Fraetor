from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.intent_translation.domain.ports import IntentTranslatorPort
    from src.shared.config.ports import SettingsRepositoryPort

logger = logging.getLogger(__name__)


class IntentTranslationUseCase:
    """意図翻訳ユースケース。

    翻訳器未設定/機能OFF/スクリーンショットなし/失敗/タイムアウト時は
    元テキストを返す(原文フォールバック)。
    """

    def __init__(
        self,
        translator: IntentTranslatorPort | None,
        *,
        settings_repository: SettingsRepositoryPort,
    ) -> None:
        self._translator = translator
        self._settings_repository = settings_repository

    async def execute(
        self, text: str, screenshot_png: bytes | None
    ) -> tuple[str, bool]:
        """変換後テキストと、変換が行われたかを返す。"""
        settings = self._settings_repository.get()
        if (
            self._translator is None
            or not settings.intent_translation_enabled
            or screenshot_png is None
        ):
            return text, False
        try:
            result = await asyncio.wait_for(
                self._translator.translate(text, screenshot_png),
                timeout=settings.intent_translation_timeout_sec,
            )
        except Exception:
            logger.exception("Intent translation failed")
            return text, False
        return result, True
