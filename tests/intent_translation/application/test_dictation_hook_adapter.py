from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.intent_translation.application.dictation_hook_adapter import (
    IntentTranslationDictationAdapter,
)


def _make_adapter() -> tuple[IntentTranslationDictationAdapter, MagicMock, MagicMock]:
    pairer = MagicMock()
    use_case = MagicMock()
    use_case.execute = AsyncMock()
    adapter = IntentTranslationDictationAdapter(pairer=pairer, use_case=use_case)
    return adapter, pairer, use_case


class TestOnSpeechStart:
    def test_delegates_to_pairer(self) -> None:
        adapter, pairer, _use_case = _make_adapter()

        adapter.on_speech_start()

        pairer.on_speech_start.assert_called_once()


class TestOnFlush:
    def test_delegates_to_pairer_with_produced_text(self) -> None:
        adapter, pairer, _use_case = _make_adapter()

        adapter.on_flush(produced_text=True)

        pairer.on_flush.assert_called_once_with(produced_text=True)


class TestReset:
    def test_delegates_to_pairer(self) -> None:
        adapter, pairer, _use_case = _make_adapter()

        adapter.reset()

        pairer.reset.assert_called_once()


class TestTransform:
    async def test_no_ready_screenshot_returns_original_text(self) -> None:
        adapter, pairer, use_case = _make_adapter()
        pairer.pop_ready.return_value = None

        result = await adapter.transform("session-1", "元テキスト")

        assert result == "元テキスト"
        use_case.execute.assert_not_awaited()

    async def test_ready_screenshot_delegates_to_use_case(self) -> None:
        adapter, pairer, use_case = _make_adapter()
        pairer.pop_ready.return_value = b"screenshot-bytes"
        use_case.execute.return_value = ("変換後の依頼文", True)

        result = await adapter.transform("session-1", "元テキスト")

        use_case.execute.assert_awaited_once_with("元テキスト", b"screenshot-bytes")
        assert result == "変換後の依頼文"
