from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.config.settings import load_settings

if TYPE_CHECKING:
    import pytest


class TestLoadSettings:
    def test_uses_defaults_when_no_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "FRAETOR_MAX_SESSION_DURATION_SEC",
            "FRAETOR_SILENCE_TIMEOUT_SEC",
            "FRAETOR_SERVER_PORT",
            "FRAETOR_SSE_KEEPALIVE_SEC",
            "FRAETOR_HISTORY_DIR",
        ):
            monkeypatch.delenv(var, raising=False)

        settings = load_settings()

        assert settings.max_session_duration_sec == 600
        assert settings.silence_timeout_sec == 120
        assert settings.server_port == 8765
        assert settings.sse_keepalive_sec == 15

    def test_env_vars_override_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FRAETOR_MAX_SESSION_DURATION_SEC", "20")
        monkeypatch.setenv("FRAETOR_SILENCE_TIMEOUT_SEC", "3")
        monkeypatch.setenv("FRAETOR_SERVER_PORT", "18765")
        monkeypatch.setenv("FRAETOR_SSE_KEEPALIVE_SEC", "1")

        settings = load_settings()

        assert settings.max_session_duration_sec == 20
        assert settings.silence_timeout_sec == 3
        assert settings.server_port == 18765
        assert settings.sse_keepalive_sec == 1

    def test_history_dir_expands_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FRAETOR_HISTORY_DIR", raising=False)

        settings = load_settings()

        assert "~" not in str(settings.history_dir)
