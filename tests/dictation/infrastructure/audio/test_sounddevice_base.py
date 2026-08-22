from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.dictation.infrastructure.audio.persistent_capture import (
    PersistentStreamCapture,
)

_SAMPLE_RATE = 16000


@patch("src.dictation.infrastructure.audio.sounddevice_base.sd")
class TestAudioCallback:
    def test_sink_exception_is_logged_and_reraised(
        self, mock_sd: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """sink 例外は握り潰さずログに残し、PortAudio へ伝播させる
        (無音 abort の原因を可視化するため)"""
        capture = PersistentStreamCapture(_SAMPLE_RATE)
        failing_sink = MagicMock(side_effect=RuntimeError("boom"))
        capture._sink = failing_sink
        mock_sd.CallbackFlags.__bool__ = lambda _self: False

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(RuntimeError, match="boom"),
        ):
            capture._audio_callback(
                np.zeros(1, dtype=np.int16), 1, object(), mock_sd.CallbackFlags()
            )

        assert "Audio capture sink raised" in caplog.text

    def test_sink_success_is_not_logged_as_error(
        self, mock_sd: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        capture = PersistentStreamCapture(_SAMPLE_RATE)
        ok_sink = MagicMock()
        capture._sink = ok_sink
        mock_sd.CallbackFlags.__bool__ = lambda _self: False

        with caplog.at_level(logging.ERROR):
            capture._audio_callback(
                np.zeros(1, dtype=np.int16), 1, object(), mock_sd.CallbackFlags()
            )

        ok_sink.assert_called_once()
        assert caplog.text == ""
