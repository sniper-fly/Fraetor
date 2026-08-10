from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.dictation.infrastructure.vad.factory import create_vad
from src.dictation.infrastructure.vad.silero_vad_detector import (
    SileroSpeechActivityDetector,
)
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository

_SAMPLE_RATE = 16000


@patch("src.dictation.infrastructure.vad.silero_vad_detector.VADIterator")
@patch("src.dictation.infrastructure.vad.silero_vad_detector.load_silero_vad")
class TestCreateVad:
    def test_creates_silero_detector(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        repo = InMemorySettingsRepository()

        vad = create_vad(settings_repository=repo, sample_rate=_SAMPLE_RATE)

        assert isinstance(vad, SileroSpeechActivityDetector)

    def test_passes_current_threshold_to_detector(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        repo = InMemorySettingsRepository(DynamicSettings(vad_threshold=0.7))

        create_vad(settings_repository=repo, sample_rate=_SAMPLE_RATE)

        assert mock_iter_cls.call_args.kwargs["threshold"] == 0.7

    def test_reads_threshold_at_each_call(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """閾値は生成時に読むため、更新後の生成には新しい値が使われる。"""
        repo = InMemorySettingsRepository(DynamicSettings(vad_threshold=0.3))
        create_vad(settings_repository=repo, sample_rate=_SAMPLE_RATE)

        repo.update(DynamicSettings(vad_threshold=0.9))
        create_vad(settings_repository=repo, sample_rate=_SAMPLE_RATE)

        thresholds = [c.kwargs["threshold"] for c in mock_iter_cls.call_args_list]
        assert thresholds == [0.3, 0.9]
