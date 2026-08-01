from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.dictation.infrastructure.audio.sounddevice_base import SounddeviceCaptureBase

if TYPE_CHECKING:
    from collections.abc import Callable

    import sounddevice as sd

logger = logging.getLogger(__name__)


class PerSessionStreamCapture(SounddeviceCaptureBase):
    """セッションごとにストリームを開閉する実装 (Linux 用)。

    録音中のみマイクデバイスを掴む。ALSA/PulseAudio には macOS CoreAudio の
    stop/close デッドロック問題がないため、毎セッション開閉できる。
    stop/close もブロッキング呼び出しのため to_thread で隔離する。
    """

    def __init__(self, sample_rate: int) -> None:
        super().__init__(sample_rate)
        self._stream: sd.InputStream | None = None

    async def start_recording(self, sink: Callable[[bytes], object]) -> None:
        self._sink = sink
        try:
            self._stream = await asyncio.to_thread(self._open_stream)
        except Exception:
            self._sink = None
            raise
        logger.info("Audio capture started (rate=%d)", self._sample_rate)

    async def stop_recording(self) -> None:
        # 旧実装と同じく、ストリームが完全に停止するまでに届いた末尾のフレームは
        # シンクに書き込む。シンクを外すのはストリームを閉じた後。
        if self._stream is not None:
            stream = self._stream
            self._stream = None
            await asyncio.to_thread(self._close_stream, stream)
            logger.info("Audio capture stopped")
        self._sink = None

    @staticmethod
    def _close_stream(stream: sd.InputStream) -> None:
        """ストリームを停止して閉じる (ブロッキング。to_thread 経由で呼ぶこと)。"""
        stream.stop()  # type: ignore[no-untyped-call]
        stream.close()  # type: ignore[no-untyped-call]
