from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.intent_translation.application.intent_translation_use_case import (
    IntentTranslationUseCase,
)
from src.shared.config.dynamic_settings import DynamicSettings


def _make_repository(
    *, enabled: bool = True, timeout_sec: int = 20
) -> MagicMock:
    repository = MagicMock()
    repository.get.return_value = DynamicSettings(
        intent_translation_enabled=enabled,
        intent_translation_timeout_sec=timeout_sec,
    )
    return repository


class TestExecute:
    async def test_translator_none_returns_original_text(self) -> None:
        use_case = IntentTranslationUseCase(
            None, settings_repository=_make_repository()
        )

        text, translated = await use_case.execute("元テキスト", b"png")

        assert text == "元テキスト"
        assert translated is False

    async def test_disabled_returns_original_text_without_calling_translator(
        self,
    ) -> None:
        translator = AsyncMock()
        use_case = IntentTranslationUseCase(
            translator, settings_repository=_make_repository(enabled=False)
        )

        text, translated = await use_case.execute("元テキスト", b"png")

        assert text == "元テキスト"
        assert translated is False
        translator.translate.assert_not_awaited()

    async def test_no_screenshot_returns_original_text_without_calling_translator(
        self,
    ) -> None:
        translator = AsyncMock()
        use_case = IntentTranslationUseCase(
            translator, settings_repository=_make_repository()
        )

        text, translated = await use_case.execute("元テキスト", None)

        assert text == "元テキスト"
        assert translated is False
        translator.translate.assert_not_awaited()

    async def test_success_returns_translated_text(self) -> None:
        translator = AsyncMock()
        translator.translate = AsyncMock(return_value="変換後の依頼文")
        use_case = IntentTranslationUseCase(
            translator, settings_repository=_make_repository()
        )

        text, translated = await use_case.execute("元テキスト", b"png-bytes")

        translator.translate.assert_awaited_once_with("元テキスト", b"png-bytes")
        assert text == "変換後の依頼文"
        assert translated is True

    async def test_translator_exception_falls_back_to_original_text(self) -> None:
        translator = AsyncMock()
        translator.translate = AsyncMock(side_effect=RuntimeError("API error"))
        use_case = IntentTranslationUseCase(
            translator, settings_repository=_make_repository()
        )

        text, translated = await use_case.execute("元テキスト", b"png")

        assert text == "元テキスト"
        assert translated is False

    async def test_timeout_falls_back_to_original_text(self) -> None:
        async def slow_translate(_text: str, _screenshot: bytes) -> str:
            await asyncio.sleep(10)
            return "遅すぎる結果"

        translator = AsyncMock()
        translator.translate = AsyncMock(side_effect=slow_translate)
        use_case = IntentTranslationUseCase(
            translator, settings_repository=_make_repository(timeout_sec=1)
        )

        text, translated = await use_case.execute("元テキスト", b"png")

        assert text == "元テキスト"
        assert translated is False
