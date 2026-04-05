from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from src import config
from src.config import init_secrets, validate_api_keys


class TestInitSecrets:
    def test_sets_keys_from_pass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """passコマンドの出力がモジュール変数に設定される。"""
        pass_values = {
            "api/azure_stt_key": "test-azure-key",
            "api/gemini": "test-gemini-key",
        }

        def fake_run(
            cmd: list[str], **_kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            entry = cmd[2]
            return subprocess.CompletedProcess(
                cmd, returncode=0, stdout=f"{pass_values[entry]}\n", stderr=""
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        init_secrets()

        assert config.AZURE_SPEECH_KEY == "test-azure-key"
        assert config.GEMINI_API_KEY == "test-gemini-key"

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
