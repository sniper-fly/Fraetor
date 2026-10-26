from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import json5
from dictation import MaiSettings

from src.shared.config.dynamic_settings import DynamicSettings, SttSettings
from src.shared.config.jsonc_settings_repository import JsoncSettingsRepository

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


class TestLoadOrCreate:
    def test_creates_file_with_defaults_when_missing(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "settings.jsonc"

        repo = JsoncSettingsRepository(path)

        assert path.exists()
        assert repo.get() == DynamicSettings()

    def test_created_file_contains_comments_and_reloads(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.jsonc"

        JsoncSettingsRepository(path)

        content = path.read_text(encoding="utf-8")
        assert "//" in content
        assert "segment_silence_sec" in content
        # 書き出した雛形が自分自身で読み直せること (JSONC として妥当)
        assert JsoncSettingsRepository(path).get() == DynamicSettings()

    def test_loads_existing_file_with_comments(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.jsonc"
        path.write_text(
            """
            {
              // 無音区切りを短くする
              "segment_silence_sec": 1.5,
              "stt": { "mai": { "locale": "en" } }, /* ロケール変更 */
            }
            """,
            encoding="utf-8",
        )

        repo = JsoncSettingsRepository(path)

        assert repo.get().segment_silence_sec == 1.5
        assert repo.get().stt.mai.locale == "en"
        # 未記載の項目は既定値で埋まる
        assert repo.get().sse_keepalive_sec == 15

    def test_falls_back_to_defaults_on_parse_error(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "settings.jsonc"
        path.write_text("{ not valid jsonc", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            repo = JsoncSettingsRepository(path)

        assert repo.get() == DynamicSettings()
        assert "falling back to defaults" in caplog.text

    def test_invalid_field_falls_back_only_for_that_field(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """不正な項目だけが既定値になり、他の項目の値は保たれる。"""
        path = tmp_path / "settings.jsonc"
        path.write_text(
            """
            {
              "vad_threshold": 5,
              "sse_keepalive_sec": 30,
              "stt": {
                "engine": "gemini",
                "mai": { "locale": "en", "timeout_sec": -1 }
              }
            }
            """,
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            settings = JsoncSettingsRepository(path).get()

        assert settings.vad_threshold == DynamicSettings().vad_threshold
        assert settings.sse_keepalive_sec == 30
        assert settings.stt.engine == "gemini"
        assert settings.stt.mai.locale == "en"
        assert settings.stt.mai.timeout_sec == 60
        assert "vad_threshold" in caplog.text
        assert "stt.mai.timeout_sec" in caplog.text

    def test_unknown_keys_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.jsonc"
        path.write_text(
            '{"mai_locale": "en", "sse_keepalive_sec": 30,'
            ' "stt": {"mai": {"no_such_key": 1}}}',
            encoding="utf-8",
        )

        settings = JsoncSettingsRepository(path).get()

        assert settings.sse_keepalive_sec == 30
        assert settings.stt == DynamicSettings().stt

    def test_cross_field_violation_resets_only_related_fields(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """無音区切りがタイムアウト以上なら、その2項目だけ既定値に戻す。"""
        path = tmp_path / "settings.jsonc"
        path.write_text(
            '{"silence_timeout_sec": 3, "segment_silence_sec": 5.0,'
            ' "sse_keepalive_sec": 30}',
            encoding="utf-8",
        )

        with caplog.at_level(logging.WARNING):
            settings = JsoncSettingsRepository(path).get()

        defaults = DynamicSettings()
        assert settings.silence_timeout_sec == defaults.silence_timeout_sec
        assert settings.segment_silence_sec == defaults.segment_silence_sec
        assert settings.sse_keepalive_sec == 30
        assert "segment_silence_sec" in caplog.text

    def test_does_not_overwrite_invalid_file_on_load(self, tmp_path: Path) -> None:
        """フォールバックは既定値を返すだけで、ユーザーのファイルを壊さない。"""
        path = tmp_path / "settings.jsonc"
        path.write_text("{ broken", encoding="utf-8")

        JsoncSettingsRepository(path)

        assert path.read_text(encoding="utf-8") == "{ broken"


class TestUpdate:
    def test_get_returns_new_value(self, tmp_path: Path) -> None:
        repo = JsoncSettingsRepository(tmp_path / "settings.jsonc")

        repo.update(DynamicSettings(segment_silence_sec=2.0, vad_threshold=0.3))

        assert repo.get().segment_silence_sec == 2.0
        assert repo.get().vad_threshold == 0.3

    def test_persists_to_file(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.jsonc"
        repo = JsoncSettingsRepository(path)

        new = DynamicSettings(
            stt=SttSettings(
                engine="gemini", mai=MaiSettings(transcribe_style="verbatim")
            )
        )

        repo.update(new)

        saved = json5.loads(path.read_text(encoding="utf-8"))
        assert saved["stt"]["engine"] == "gemini"
        assert saved["stt"]["mai"]["transcribe_style"] == "verbatim"
        assert JsoncSettingsRepository(path).get() == new

    def test_rewrites_all_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "settings.jsonc"
        repo = JsoncSettingsRepository(path)

        repo.update(DynamicSettings(sse_keepalive_sec=30))

        written = json5.loads(path.read_text(encoding="utf-8"))
        assert set(written) == set(DynamicSettings.model_fields)
