from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.shared.config.dynamic_settings import DynamicSettings


class TestDefaults:
    def test_defaults_match_plan(self) -> None:
        settings = DynamicSettings()

        assert settings.max_session_duration_sec == 600
        assert settings.silence_timeout_sec == 120
        assert settings.segment_silence_sec == 3.0
        assert settings.vad_threshold == 0.5
        assert settings.mai_locale == "ja"
        assert settings.mai_model_name == "mai-transcribe-1"
        assert settings.mai_timeout_sec == 60
        assert settings.proofread_timeout_sec == 15
        assert settings.shutdown_delay_sec == 0.5
        assert settings.sse_keepalive_sec == 15


class TestSilenceThresholdValidation:
    def test_rejects_segment_silence_equal_to_timeout(self) -> None:
        with pytest.raises(ValidationError, match="segment_silence_sec"):
            DynamicSettings(silence_timeout_sec=3, segment_silence_sec=3.0)

    def test_rejects_segment_silence_greater_than_timeout(self) -> None:
        with pytest.raises(ValidationError, match="segment_silence_sec"):
            DynamicSettings(silence_timeout_sec=3, segment_silence_sec=5.0)

    def test_accepts_segment_silence_less_than_timeout(self) -> None:
        settings = DynamicSettings(silence_timeout_sec=3, segment_silence_sec=2.5)

        assert settings.segment_silence_sec == 2.5


class TestRangeValidation:
    @pytest.mark.parametrize("threshold", [-0.1, 1.1])
    def test_rejects_vad_threshold_outside_zero_to_one(self, threshold: float) -> None:
        with pytest.raises(ValidationError, match="vad_threshold"):
            DynamicSettings(vad_threshold=threshold)

    def test_rejects_non_positive_durations(self) -> None:
        with pytest.raises(ValidationError, match="segment_silence_sec"):
            DynamicSettings(segment_silence_sec=0.0)
