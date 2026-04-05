from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sounddevice as sd

from src.config import STT_SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

logger = logging.getLogger(__name__)


class AudioCapture:
    """マイク音声をキャプチャし、PCMデータをシンクに書き込む。"""

    def __init__(
        self,
        write_audio: Callable[[bytes], object],
        sample_rate: int = STT_SAMPLE_RATE,
    ) -> None:
        self._write_audio = write_audio
        self._sample_rate = sample_rate
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        self._stream = sd.InputStream(  # type: ignore[no-untyped-call]
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
        )
        self._stream.start()  # type: ignore[no-untyped-call]
        logger.info("Audio capture started (rate=%d)", self._sample_rate)

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()  # type: ignore[no-untyped-call]
            self._stream.close()  # type: ignore[no-untyped-call]
            self._stream = None
            logger.info("Audio capture stopped")

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,  # noqa: ARG002
        time_info: object,  # noqa: ARG002
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("Audio capture status: %s", status)
        self._write_audio(indata.tobytes())
