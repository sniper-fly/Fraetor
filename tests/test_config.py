from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock

import pytest

from src import config
from src.config import init_secrets, validate_api_keys

_FAKE_SA_JSON = json.dumps({"project_id": "test-project", "type": "service_account"})


def _fake_pass_outputs() -> dict[str, str]:
    return {
        "api/azure_stt_key": "test-azure-key\n",
        "api/azure_mai_resource": "test-mai-key\n",
        "gc/ai_service_account": _FAKE_SA_JSON + "\n",
    }


class TestInitSecrets:
    def test_sets_keys_from_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """passコマンドの出力がモジュール変数に設定される。"""
        outputs = _fake_pass_outputs()

        def fake_run(
            cmd: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            entry = cmd[2]
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=outputs[entry], stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        init_secrets()

        assert config.AZURE_SPEECH_KEY == "test-azure-key"
        assert config.MAI_API_KEY == "test-mai-key"
        assert config.VERTEX_SA_INFO["project_id"] == "test-project"
        assert config.VERTEX_PROJECT == "test-project"

    def test_raises_on_pass_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """passコマンド失敗時にRuntimeErrorが発生する。"""
        failed = subprocess.CompletedProcess(
            ["pass", "show", "api/azure_stt_key"],
            returncode=1,
            stdout="",
            stderr="entry not found",
        )
        monkeypatch.setattr(subprocess, "run", MagicMock(return_value=failed))

        with pytest.raises(
            RuntimeError, match="pass show api/azure_stt_key に失敗しました"
        ):
            init_secrets()

    def test_raises_on_vertex_pass_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vertex SAのpassコマンド失敗時にRuntimeErrorが発生する。"""
        outputs = {
            "api/azure_stt_key": "azure-key\n",
            "api/azure_mai_resource": "mai-key\n",
        }

        def fake_run(
            cmd: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            entry = cmd[2]
            if entry in outputs:
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout=outputs[entry], stderr=""
                )
            return subprocess.CompletedProcess(
                cmd, returncode=1, stdout="", stderr="entry not found"
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        with pytest.raises(
            RuntimeError,
            match="pass show gc/ai_service_account に失敗しました",
        ):
            init_secrets()


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
