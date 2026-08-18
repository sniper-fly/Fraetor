from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.intent_translation.infrastructure.azure_openai_intent_translator import (
    AzureOpenAIIntentTranslator,
)

_MODULE = (
    "src.intent_translation.infrastructure.azure_openai_intent_translator"
    ".AsyncAzureOpenAI"
)


def _make_translator(mock_cls: MagicMock) -> AzureOpenAIIntentTranslator:
    return AzureOpenAIIntentTranslator(
        endpoint="https://example.cognitiveservices.azure.com/",
        api_key="test-key",
        deployment="gpt-5.6-luna",
        api_version="2024-08-01-preview",
        prompt="システムプロンプト",
    )


def _stub_response(content: str | None) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestTranslate:
    @patch(_MODULE)
    async def test_uses_max_completion_tokens_not_max_tokens(
        self, mock_cls: MagicMock
    ) -> None:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(
            return_value=_stub_response("変換後の依頼文")
        )
        translator = _make_translator(mock_cls)

        await translator.translate("元テキスト", b"png-bytes")

        _args, kwargs = mock_client.chat.completions.create.call_args
        assert kwargs["max_completion_tokens"] == 2500
        assert "max_tokens" not in kwargs

    @patch(_MODULE)
    async def test_empty_text_returns_immediately_without_calling_api(
        self, mock_cls: MagicMock
    ) -> None:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock()
        translator = _make_translator(mock_cls)

        result = await translator.translate("   ", b"png-bytes")

        assert result == "   "
        mock_client.chat.completions.create.assert_not_awaited()

    @patch(_MODULE)
    async def test_empty_content_falls_back_to_original_text(
        self, mock_cls: MagicMock
    ) -> None:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(
            return_value=_stub_response(None)
        )
        translator = _make_translator(mock_cls)

        result = await translator.translate("元テキスト", b"png-bytes")

        assert result == "元テキスト"

    @patch(_MODULE)
    async def test_success_returns_stripped_content(self, mock_cls: MagicMock) -> None:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(
            return_value=_stub_response("  変換後の依頼文  ")
        )
        translator = _make_translator(mock_cls)

        result = await translator.translate("元テキスト", b"png-bytes")

        assert result == "変換後の依頼文"

    @patch(_MODULE)
    async def test_sends_image_as_data_url(self, mock_cls: MagicMock) -> None:
        mock_client = mock_cls.return_value
        mock_client.chat.completions.create = AsyncMock(
            return_value=_stub_response("変換後")
        )
        translator = _make_translator(mock_cls)

        await translator.translate("元テキスト", b"png-bytes")

        _args, kwargs = mock_client.chat.completions.create.call_args
        user_content = kwargs["messages"][1]["content"]
        image_part = next(
            part for part in user_content if part["type"] == "image_url"
        )
        assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
