from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.dictation.infrastructure.audio.sounddevice_base import SounddeviceCaptureBase

if TYPE_CHECKING:
    from collections.abc import Callable

    import sounddevice as sd

logger = logging.getLogger(__name__)


class PersistentStreamCapture(SounddeviceCaptureBase):
    """ストリームを常駐させる実装 (macOS 用)。

    macOS の PortAudio (CoreAudio バックエンド, v19.7.0 時点) には、
    `stream.stop()/close()` が CoreAudio IO スレッドのリスナー発火と重なると
    ABBA デッドロックしてプロセス全体が固まる既知のバグがある。
    このためストリームは初回録音時に一度だけ開き、プロセス終了まで閉じない
    (終了時は OS がデバイスを回収する)。録音 ON/OFF はシンク差し替えのみで行う。

    トレードオフ: 初回録音以降、マイクが常時オープンになる
    (macOS ではマイク使用中インジケータが点灯し続ける)。

    CoreAudio 側の要因 (省電力・デバイス切断等) でストリームが PortAudio 側
    から無音で abort されることがある。`start_recording` の度に
    `stream.active` を確認し、非アクティブなら (close() は呼ばずに) 再オープン
    することで自己修復する。
    """

    def __init__(self, sample_rate: int) -> None:
        super().__init__(sample_rate)
        self._stream: sd.InputStream | None = None

    async def start_recording(self, sink: Callable[[bytes], object]) -> None:
        if self._stream is not None and not self._stream.active:
            # コールバック例外等で PortAudio が無音で abort した状態。
            # 既知の stop()/close() デッドロックバグを踏まないよう、古い
            # ストリームは明示的に停止/close せず参照を捨てて再オープンする。
            logger.warning("Persistent audio stream became inactive; reopening")
            self._stream = None
        if self._stream is None:
            self._stream = await asyncio.to_thread(self._open_stream)
            logger.info("Persistent audio stream opened (rate=%d)", self._sample_rate)
        self._sink = sink
        logger.info("Audio capture started (rate=%d)", self._sample_rate)

    async def stop_recording(self) -> None:
        self._sink = None
        logger.info("Audio capture stopped (stream kept open)")
