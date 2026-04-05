from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import validate_api_keys

if TYPE_CHECKING:
    import pytest


class TestValidateApiKeys:
    def test_no_warnings_when_both_keys_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "azure-key")
        monkeypatch.setattr("src.config.GEMINI_API_KEY", "gemini-key")

        assert validate_api_keys() == []

    def test_warns_when_azure_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "")
        monkeypatch.setattr("src.config.GEMINI_API_KEY", "gemini-key")

        warnings = validate_api_keys()

        assert len(warnings) == 1
        assert "AZURE_SPEECH_KEY" in warnings[0]

    def test_warns_when_gemini_key_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "azure-key")
        monkeypatch.setattr("src.config.GEMINI_API_KEY", "")

        warnings = validate_api_keys()

        assert len(warnings) == 1
        assert "GEMINI_API_KEY" in warnings[0]

    def test_warns_for_both_keys_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "")
        monkeypatch.setattr("src.config.GEMINI_API_KEY", "")

        warnings = validate_api_keys()

        assert len(warnings) == 2
