from __future__ import annotations

import logging
import time

import numpy as np
import torch
from silero_vad import VADIterator, load_silero_vad

from src.config import STT_SAMPLE_RATE, VAD_THRESHOLD

logger = logging.getLogger(__name__)

_WINDOW_SAMPLES = 512  # Silero VAD が 16kHz 入力に要求する固定ウィンドウ長
_PCM_SAMPLE_WIDTH_BYTES = 2  # 16-bit


class SpeechActivityDetector:
    """Silero VAD で発話区間を検出し、最後に発話を検知した時刻を保持する。

    sounddevice のコールバックが渡す PCM チャンクは可変長だが、Silero VAD は
    512 サンプル (16kHz 時) 固定のウィンドウしか受け付けないため、内部バッファで
    512 サンプル単位に区切って推論する。
    """

    def __init__(self, sample_rate: int = STT_SAMPLE_RATE) -> None:
        model = load_silero_vad()
        self._iterator = VADIterator(
            model, sampling_rate=sample_rate, threshold=VAD_THRESHOLD
        )
        self._buffer = bytearray()
        self._last_speech_time: float = time.monotonic()

    @property
    def last_speech_time(self) -> float:
        return self._last_speech_time

    def feed(self, pcm_bytes: bytes) -> None:
        """PCM (16kHz/16bit/mono) を受け取り、512サンプル単位でVAD推論する。

        推論失敗はログに記録して握り潰す。VAD側の不具合で録音・STTを
        止めないため。
        """
        try:
            self._buffer.extend(pcm_bytes)
            window_bytes = _WINDOW_SAMPLES * _PCM_SAMPLE_WIDTH_BYTES
            while len(self._buffer) >= window_bytes:
                chunk = bytes(self._buffer[:window_bytes])
                del self._buffer[:window_bytes]
                self._feed_window(chunk)
        except Exception:
            logger.exception("VAD inference failed; skipping this chunk")

    def _feed_window(self, window_bytes: bytes) -> None:
        samples = np.frombuffer(window_bytes, dtype=np.int16)
        audio = samples.astype(np.float32) / 32768.0
        result = self._iterator(torch.from_numpy(audio))
        # triggered (発話中) の間は毎ウィンドウ更新し続け、end (発話終了確定)
        # イベントでも更新する。start イベントの瞬間だけ更新すると、長い発話の
        # 途中で無音タイマーが発話開始時刻のまま固定されてしまう。
        speech_ended = result is not None and "end" in result
        if self._iterator.triggered or speech_ended:
            self._last_speech_time = time.monotonic()
