from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.stt_azure import AzureSttClient
from src.stt_factory import create_stt_engine
from src.stt_mai import MaiTranscribeClient


class TestCreateSttEngine:
    @patch("src.stt_factory.config")
    @patch("src.stt_azure.speechsdk")
    def test_returns_azure_when_engine_is_azure(
        self, mock_sdk: MagicMock, mock_config: MagicMock
    ) -> None:
        del mock_sdk
        mock_config.STT_ENGINE = "azure"
        engine = create_stt_engine(asyncio.Queue())
        assert isinstance(engine, AzureSttClient)

    @patch("src.stt_factory.config")
    @patch("src.stt_mai.TranscriptionClient")
    def test_returns_mai_when_engine_is_mai(
        self, mock_client: MagicMock, mock_config: MagicMock
    ) -> None:
        del mock_client
        mock_config.STT_ENGINE = "mai"
        engine = create_stt_engine(asyncio.Queue())
        assert isinstance(engine, MaiTranscribeClient)

    @patch("src.stt_factory.config")
    def test_raises_for_unknown_engine(self, mock_config: MagicMock) -> None:
        mock_config.STT_ENGINE = "unknown"
        with pytest.raises(ValueError, match="Unknown STT_ENGINE"):
            create_stt_engine(asyncio.Queue())
