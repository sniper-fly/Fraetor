from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.config.dynamic_settings import DynamicSettings
from src.shared.config.settings import Settings, load_settings

if TYPE_CHECKING:
    import pytest


class TestLoadSettings:
    def test_uses_defaults_when_no_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in ("FRAETOR_SERVER_PORT", "FRAETOR_HISTORY_DIR"):
            monkeypatch.delenv(var, raising=False)

        settings = load_settings()

        assert settings.server_port == 8765
        assert settings.stt_sample_rate == 16000

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FRAETOR_SERVER_PORT", "18765")

        settings = load_settings()

        assert settings.server_port == 18765

    def test_history_dir_expands_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FRAETOR_HISTORY_DIR", raising=False)

        settings = load_settings()

        assert "~" not in str(settings.history_dir)


class TestStaticDynamicSeparation:
    def test_no_field_is_defined_in_both_models(self) -> None:
        """動的化した値が `Settings` に残っていない (二重定義の防止)。

        両方に存在すると「どちらが効いているか」が読み手に判別できず、
        設定画面から変更しても反映されない値が生まれる。
        """
        overlap = set(Settings.model_fields) & set(DynamicSettings.model_fields)

        assert overlap == set()
