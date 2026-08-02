from __future__ import annotations

import asyncio
import contextlib
import logging
import wave
from typing import TYPE_CHECKING

from src.dictation.infrastructure.audio.sounddevice_base import SounddeviceCaptureBase

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK_DURATION_SEC = 0.1


class FileAudioCapture(SounddeviceCaptureBase):
    """WAV ファイルを実時間ペースで読み込み、マイク入力を模擬する実装。

    E2E テストでハードウェアマイクへの依存を避けつつ、VAD の発話検知や
    セッションタイムアウトの実時間ロジックを意味のある形で検証するために
    使う。ファイル終端に達したらそれ以上コールバックを呼ばなくなる
    (無音区間として振る舞う)。
    """

    def __init__(self, wav_path: Path, sample_rate: int) -> None:
        super().__init__(sample_rate)
        self._wav_path = wav_path
        self._task: asyncio.Task[None] | None = None

    async def start_recording(self, sink: Callable[[bytes], object]) -> None:
        with wave.open(str(self._wav_path), "rb") as wf:
            if wf.getframerate() != self._sample_rate:
                msg = (
                    f"WAV サンプルレートが不一致です: "
                    f"{wf.getframerate()} != {self._sample_rate}"
                )
                raise ValueError(msg)
        self._sink = sink
        self._task = asyncio.create_task(self._play())
        logger.info("File audio capture started (path=%s)", self._wav_path)

    def set_wav_path(self, wav_path: Path) -> None:
        """次回の start_recording() で読み込む WAV ファイルを切り替える。

        E2E テストが同一サーバープロセス内で異なる発話内容のセッションを
        連続して作るために使う (本番コードパスからは呼ばれない)。
        """
        self._wav_path = wav_path

    async def stop_recording(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._sink = None
        logger.info("File audio capture stopped")

    async def _play(self) -> None:
        chunk_frames = int(self._sample_rate * _CHUNK_DURATION_SEC)
        with wave.open(str(self._wav_path), "rb") as wf:
            while True:
                chunk = wf.readframes(chunk_frames)
                if not chunk:
                    return
                sink = self._sink
                if sink is not None:
                    sink(chunk)
                await asyncio.sleep(_CHUNK_DURATION_SEC)
