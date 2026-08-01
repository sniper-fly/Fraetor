from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sounddevice as sd

from src.dictation.domain.ports import AudioCapturePort

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

logger = logging.getLogger(__name__)


class SounddeviceCaptureBase(AudioCapturePort):
    """sounddevice 依存の共通実装。

    PCM データの取得方法 (16kHz/16-bit/mono、コールバックからシンクへの書き込み)
    は共通で、ストリームのライフサイクル戦略だけが実装ごとに異なる。
    ブロックし得る PortAudio 呼び出しは各実装が asyncio.to_thread で
    イベントループから隔離する。
    """

    def __init__(self, sample_rate: int) -> None:
        self._sample_rate = sample_rate
        self._sink: Callable[[bytes], object] | None = None

    def _open_stream(self) -> sd.InputStream:
        """ストリームを開いて開始する (ブロッキング。to_thread 経由で呼ぶこと)。"""
        stream = sd.InputStream(  # type: ignore[no-untyped-call]
            samplerate=self._sample_rate,
            channels=1,
            dtype="int16",
            callback=self._audio_callback,
        )
        try:
            stream.start()  # type: ignore[no-untyped-call]
        except Exception:
            stream.close()  # type: ignore[no-untyped-call]
            raise
        return stream

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,  # noqa: ARG002
        time_info: object,  # noqa: ARG002
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("Audio capture status: %s", status)
        sink = self._sink
        if sink is not None:
            sink(indata.tobytes())
