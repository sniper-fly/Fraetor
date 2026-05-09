from __future__ import annotations

from typing import TYPE_CHECKING

from src import config
from src.config import init_secrets, validate_api_keys
from src.secrets_loader import Secrets

if TYPE_CHECKING:
    import pytest


class TestInitSecrets:
    def test_assigns_module_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """load_secrets() の戻り値が config モジュール変数に反映される。"""
        fake = Secrets(
            azure_speech_key="azure-key",
            mai_api_key="mai-key",
            mai_endpoint="https://mai.example/",
            vertex_sa_info={"project_id": "test-project", "type": "service_account"},
            vertex_project="test-project",
        )
        monkeypatch.setattr("src.config.load_secrets", lambda: fake)

        init_secrets()

        assert config.AZURE_SPEECH_KEY == "azure-key"
        assert config.MAI_API_KEY == "mai-key"
        assert config.MAI_ENDPOINT == "https://mai.example/"
        assert config.VERTEX_SA_INFO == {
            "project_id": "test-project",
            "type": "service_account",
        }
        assert config.VERTEX_PROJECT == "test-project"


class TestValidateApiKeys:
    def test_no_warnings_when_azure_engine_and_keys_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.STT_ENGINE", "azure")
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "azure-key")
        monkeypatch.setattr("src.config.MAI_API_KEY", "")
        monkeypatch.setattr("src.config.VERTEX_SA_INFO", {"project_id": "test-project"})

        assert validate_api_keys() == []

    def test_no_warnings_when_mai_engine_and_keys_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.STT_ENGINE", "mai")
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "")
        monkeypatch.setattr("src.config.MAI_API_KEY", "mai-key")
        monkeypatch.setattr("src.config.VERTEX_SA_INFO", {"project_id": "test-project"})

        assert validate_api_keys() == []

    def test_warns_when_azure_key_missing_under_azure_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.STT_ENGINE", "azure")
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "")
        monkeypatch.setattr("src.config.MAI_API_KEY", "mai-key")
        monkeypatch.setattr("src.config.VERTEX_SA_INFO", {"project_id": "test-project"})

        warnings = validate_api_keys()

        assert len(warnings) == 1
        assert "AZURE_SPEECH_KEY" in warnings[0]

    def test_warns_when_mai_key_missing_under_mai_engine(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.STT_ENGINE", "mai")
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "azure-key")
        monkeypatch.setattr("src.config.MAI_API_KEY", "")
        monkeypatch.setattr("src.config.VERTEX_SA_INFO", {"project_id": "test-project"})

        warnings = validate_api_keys()

        assert len(warnings) == 1
        assert "MAI_API_KEY" in warnings[0]

    def test_warns_when_vertex_sa_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.config.STT_ENGINE", "azure")
        monkeypatch.setattr("src.config.AZURE_SPEECH_KEY", "azure-key")
        monkeypatch.setattr("src.config.MAI_API_KEY", "mai-key")
        monkeypatch.setattr("src.config.VERTEX_SA_INFO", {})

        warnings = validate_api_keys()

        assert len(warnings) == 1
        assert "VERTEX_SA_INFO" in warnings[0]
