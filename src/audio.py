from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import sounddevice as sd

from src.config import STT_SAMPLE_RATE

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

logger = logging.getLogger(__name__)


class AudioCapture:
    """マイク音声を常駐ストリームでキャプチャし、録音中のみPCMをシンクに書き込む。

    macOS の PortAudio (CoreAudio バックエンド) には、`stream.stop()/close()` が
    CoreAudio IO スレッドのリスナー発火とタイミングが重なると ABBA デッドロックする
    既知のバグがある。これを踏まないため、ストリームは初回録音時に一度だけ開き、
    プロセス終了まで閉じない (終了時は OS がデバイスを回収する)。
    録音の ON/OFF はコールバックの書き込み先 (シンク) の差し替えのみで行う。

    ストリームを開く操作も CoreAudio へ降りる同期呼び出しでブロックし得るため、
    `asyncio.to_thread` でイベントループから隔離する。
    """

    def __init__(self, sample_rate: int = STT_SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._stream: sd.InputStream | None = None
        self._sink: Callable[[bytes], object] | None = None

    async def ensure_open(self) -> None:
        """常駐ストリームを開く (初回のみ)。2回目以降は何もしない。"""
        if self._stream is None:
            await asyncio.to_thread(self._open_stream)

    def _open_stream(self) -> None:
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
        self._stream = stream
        logger.info("Audio stream opened (rate=%d)", self._sample_rate)

    def start_recording(self, sink: Callable[[bytes], object]) -> None:
        """コールバックの書き込み先を設定し、録音を開始する。"""
        self._sink = sink
        logger.info("Audio capture started (rate=%d)", self._sample_rate)

    def stop_recording(self) -> None:
        """書き込み先を外して録音を停止する。ストリームは開いたまま維持する。"""
        self._sink = None
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
        sink = self._sink
        if sink is not None:
            sink(indata.tobytes())
