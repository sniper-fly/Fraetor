from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.domain.ports import (
    RecognizedTextTransformPort,
    SegmentLifecycleHookPort,
)

if TYPE_CHECKING:
    from src.intent_translation.application.intent_translation_use_case import (
        IntentTranslationUseCase,
    )
    from src.intent_translation.application.segment_screenshot_pairer import (
        SegmentScreenshotPairer,
    )


class IntentTranslationDictationAdapter(
    SegmentLifecycleHookPort, RecognizedTextTransformPort
):
    """dictationの汎用フックポートを実装し、意図翻訳レイヤーへ橋渡しする唯一の接続点。

    dictationモジュールはこのクラスを`SegmentLifecycleHookPort`/
    `RecognizedTextTransformPort`としてのみ知り、intent_translation側の
    具象には依存しない(境界づけられたコンテキスト間の逆依存を避ける)。
    """

    def __init__(
        self,
        *,
        pairer: SegmentScreenshotPairer,
        use_case: IntentTranslationUseCase,
    ) -> None:
        self._pairer = pairer
        self._use_case = use_case

    def on_speech_start(self) -> None:
        self._pairer.on_speech_start()

    def on_flush(self, *, produced_text: bool) -> None:
        self._pairer.on_flush(produced_text=produced_text)

    def reset(self) -> None:
        self._pairer.reset()

    async def transform(self, _session_id: str, text: str) -> str:
        screenshot = self._pairer.pop_ready()
        if screenshot is None:
            return text
        translated, _ = await self._use_case.execute(text, screenshot)
        return translated
