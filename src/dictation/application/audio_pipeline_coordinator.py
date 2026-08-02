from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.dictation.domain.ports import (
        AudioCapturePort,
        SpeechActivityDetectorPort,
        SttEnginePort,
    )


class AudioPipelineCoordinator:
    """STT/VADの起動停止と、録音コールバックのfanoutを制御する。

    セッション開始のたびに新しい STT エンジンインスタンスと専用の
    イベントキューを生成する (`stt_engine_factory` の呼び出しごとの都度 new)。
    セッションごとにキューを分離することで、キュー化された文字起こし
    ジョブの結果が別セッションの処理に混線することを防ぐ。
    """

    def __init__(
        self,
        audio_capture: AudioCapturePort,
        stt_engine_factory: Callable[[asyncio.Queue[dict[str, str]]], SttEnginePort],
        vad_factory: Callable[[], SpeechActivityDetectorPort],
    ) -> None:
        self._audio_capture = audio_capture
        self._stt_engine_factory = stt_engine_factory
        self._vad_factory = vad_factory
        self._stt_client: SttEnginePort | None = None
        self._event_queue: asyncio.Queue[dict[str, str]] | None = None
        self._vad: SpeechActivityDetectorPort | None = None
        self._session_start_time: float = time.monotonic()

    @property
    def stt_client(self) -> SttEnginePort | None:
        return self._stt_client

    @property
    def event_queue(self) -> asyncio.Queue[dict[str, str]] | None:
        return self._event_queue

    def last_speech_time(self) -> float:
        """最後に発話を検知した時刻。VAD未起動時はセッション開始時刻を返す。"""
        return self._vad.last_speech_time if self._vad else self._session_start_time

    async def start(self) -> None:
        """STT接続 → マイクキャプチャ開始。失敗時は例外を伝播する。"""
        self._session_start_time = time.monotonic()
        self._event_queue = asyncio.Queue()
        self._stt_client = self._stt_engine_factory(self._event_queue)
        try:
            await self._stt_client.start()
        except Exception:
            self._stt_client = None
            self._event_queue = None
            raise
        self._vad = self._vad_factory()
        try:
            await self._audio_capture.start_recording(self._on_audio_chunk)
        except Exception:
            await self._stt_client.stop()
            self._stt_client = None
            self._event_queue = None
            self._vad = None
            raise

    async def stop(self) -> tuple[SttEnginePort, asyncio.Queue[dict[str, str]]] | None:
        """録音を停止し、STTクライアントと専用イベントキューの所有権を返す。

        STT の stop() (文字起こし本体、重い処理) はここでは呼ばない。
        呼び出し元が `TranscriptionQueue` にジョブとして委譲する。
        """
        await self._audio_capture.stop_recording()

        stt_client = self._stt_client
        event_queue = self._event_queue
        self._stt_client = None
        self._event_queue = None
        self._vad = None

        if stt_client is None or event_queue is None:
            return None
        return stt_client, event_queue

    def _on_audio_chunk(self, buffer: bytes) -> None:
        """PCMチャンクをSTTとVADの両方に転送する。"""
        if self._stt_client:
            self._stt_client.feed_audio(buffer)
        if self._vad:
            self._vad.feed(buffer)
