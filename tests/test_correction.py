from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import pytest

from src.correction import GeminiCorrectionClient


def _make_message(text: str | None) -> MagicMock:
    """output_transcription 付きの LiveServerMessage モックを生成する。"""
    transcription = MagicMock()
    transcription.text = text

    server_content = MagicMock()
    server_content.output_transcription = transcription

    msg = MagicMock()
    msg.server_content = server_content
    return msg


async def _async_iter(*items: object) -> AsyncIterator[object]:
    for item in items:
        yield item


def _setup_genai_mock(
    mock_genai: MagicMock,
) -> tuple[MagicMock, MagicMock]:
    """genai モックをセットアップし、(mock_client, mock_session) を返す。"""
    mock_session = MagicMock()
    mock_session.send_realtime_input = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_session
    mock_cm.__aexit__.return_value = False

    mock_client = mock_genai.Client.return_value
    mock_client.aio.live.connect.return_value = mock_cm

    return mock_client, mock_session


@patch("src.correction.genai")
class TestConnect:
    async def test_connects_with_correct_config(self, mock_genai: MagicMock) -> None:
        """design.md: Gemini Live API セッション接続"""
        mock_client, _ = _setup_genai_mock(mock_genai)

        client = GeminiCorrectionClient()
        await client.connect()

        mock_client.aio.live.connect.assert_called_once()
        call_kwargs = mock_client.aio.live.connect.call_args
        assert call_kwargs.kwargs["model"] == "gemini-3.1-flash-live-preview"

        await client.disconnect()

    async def test_session_is_set_after_connect(self, mock_genai: MagicMock) -> None:
        _, mock_session = _setup_genai_mock(mock_genai)

        client = GeminiCorrectionClient()
        await client.connect()

        assert client._session is mock_session

        await client.disconnect()


@patch("src.correction.genai")
class TestCorrect:
    async def test_returns_corrected_text(self, mock_genai: MagicMock) -> None:
        """design.md: recognized → Gemini Live API → corrected"""
        _, mock_session = _setup_genai_mock(mock_genai)
        mock_session.receive.return_value = _async_iter(
            _make_message("校正された"), _make_message("テキスト")
        )

        client = GeminiCorrectionClient()
        await client.connect()
        result = await client.correct("元テキスト")

        assert result == "校正されたテキスト"
        mock_session.send_realtime_input.assert_called_once_with(text="元テキスト")

        await client.disconnect()

    async def test_returns_original_when_no_text_in_response(
        self, mock_genai: MagicMock
    ) -> None:
        _, mock_session = _setup_genai_mock(mock_genai)
        mock_session.receive.return_value = _async_iter(_make_message(None))

        client = GeminiCorrectionClient()
        await client.connect()
        result = await client.correct("元テキスト")

        assert result == "元テキスト"

        await client.disconnect()

    async def test_raises_when_not_connected(self, mock_genai: MagicMock) -> None:
        _setup_genai_mock(mock_genai)

        client = GeminiCorrectionClient()
        with pytest.raises(RuntimeError, match="Not connected"):
            await client.correct("テスト")


@patch("src.correction.genai")
class TestDisconnect:
    async def test_clears_session(self, mock_genai: MagicMock) -> None:
        """design.md: セッション終了後 → Gemini Live API セッション切断"""
        _setup_genai_mock(mock_genai)

        client = GeminiCorrectionClient()
        await client.connect()
        await client.disconnect()

        assert client._session is None
        assert client._exit_stack is None

    async def test_noop_when_not_connected(self, mock_genai: MagicMock) -> None:
        _setup_genai_mock(mock_genai)

        client = GeminiCorrectionClient()
        await client.disconnect()
