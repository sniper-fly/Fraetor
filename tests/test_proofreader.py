from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.proofreader import Proofreader


def _make_proofreader(mock_genai: MagicMock) -> Proofreader:
    with patch(
        "src.proofreader.service_account.Credentials.from_service_account_info",
        return_value=MagicMock(),
    ):
        return Proofreader(
            sa_info={"project_id": "test-project", "type": "service_account"},
            project="test-project",
            location="global",
            model="gemini-3.1-flash-lite-preview",
            prompt="校正してください",
        )


@patch("src.proofreader.genai")
class TestProofread:
    async def test_returns_proofread_text(self, mock_genai: MagicMock) -> None:
        """LLMの校正結果が返される。"""
        proofreader = _make_proofreader(mock_genai)
        mock_response = MagicMock()
        mock_response.text = "校正済みテキスト"
        mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        result = await proofreader.proofread("元のテキスト")

        assert result == "校正済みテキスト"

    async def test_sends_prompt_with_text(self, mock_genai: MagicMock) -> None:
        """プロンプトとテキストが結合されてLLMに送信される。"""
        proofreader = _make_proofreader(mock_genai)
        mock_response = MagicMock()
        mock_response.text = "結果"
        mock_generate = AsyncMock(return_value=mock_response)
        mock_genai.Client.return_value.aio.models.generate_content = mock_generate

        await proofreader.proofread("入力テキスト")

        mock_generate.assert_called_once_with(
            model="gemini-3.1-flash-lite-preview",
            contents="校正してください\n\n入力テキスト",
        )

    async def test_empty_text_returns_as_is(self, mock_genai: MagicMock) -> None:
        """空テキストはAPI呼び出しなしでそのまま返す。"""
        proofreader = _make_proofreader(mock_genai)
        mock_generate = AsyncMock()
        mock_genai.Client.return_value.aio.models.generate_content = mock_generate

        result = await proofreader.proofread("")

        assert result == ""
        mock_generate.assert_not_called()

    async def test_whitespace_only_returns_as_is(self, mock_genai: MagicMock) -> None:
        """空白のみのテキストはAPI呼び出しなしでそのまま返す。"""
        proofreader = _make_proofreader(mock_genai)
        mock_generate = AsyncMock()
        mock_genai.Client.return_value.aio.models.generate_content = mock_generate

        result = await proofreader.proofread("   ")

        assert result == "   "
        mock_generate.assert_not_called()

    async def test_api_error_propagates(self, mock_genai: MagicMock) -> None:
        """APIエラーはそのまま伝播する。"""
        proofreader = _make_proofreader(mock_genai)
        mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with pytest.raises(RuntimeError, match="API error"):
            await proofreader.proofread("テスト")

    async def test_none_response_returns_original(self, mock_genai: MagicMock) -> None:
        """LLMがNoneを返した場合、元のテキストを返す。"""
        proofreader = _make_proofreader(mock_genai)
        mock_response = MagicMock()
        mock_response.text = None
        mock_genai.Client.return_value.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        result = await proofreader.proofread("元のテキスト")

        assert result == "元のテキスト"
