from __future__ import annotations

import asyncio
import logging

import azure.cognitiveservices.speech as speechsdk

from src.config import (
    AZURE_LANGUAGE,
    AZURE_REGION,
    AZURE_SPEECH_KEY,
    STABLE_PARTIAL_RESULT_THRESHOLD,
    STT_SAMPLE_RATE,
)

logger = logging.getLogger(__name__)


class AzureSttClient:
    """Azure Speech-to-Text ストリーミングクライアント。

    セッション毎に生成・破棄する。write_audio にPCMバイトを渡すと
    Azure STT に送信され、認識結果が stt_event_queue に入る。
    """

    def __init__(
        self,
        stt_event_queue: asyncio.Queue[dict[str, str]],
    ) -> None:
        self._queue = stt_event_queue
        self._loop: asyncio.AbstractEventLoop | None = None

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=STT_SAMPLE_RATE,
            bits_per_sample=16,
            channels=1,
        )
        self._push_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=stream_format,
        )
        audio_config = speechsdk.audio.AudioConfig(stream=self._push_stream)

        speech_config = speechsdk.SpeechConfig(
            subscription=AZURE_SPEECH_KEY,
            region=AZURE_REGION,
            speech_recognition_language=AZURE_LANGUAGE,
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceResponse_StablePartialResultThreshold,
            str(STABLE_PARTIAL_RESULT_THRESHOLD),
        )

        self._recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
        )
        self._recognizer.recognizing.connect(self._on_recognizing)
        self._recognizer.recognized.connect(self._on_recognized)
        self._recognizer.canceled.connect(self._on_canceled)

    def write_audio(self, buffer: bytes) -> None:
        """PCM音声データを Azure STT に送信する。"""
        self._push_stream.write(buffer)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self._loop.run_in_executor(
            None,
            self._recognizer.start_continuous_recognition_async().get,
        )
        logger.info("Azure STT started")

    async def stop(self) -> None:
        self._push_stream.close()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._recognizer.stop_continuous_recognition_async().get,
        )
        self._loop = None
        logger.info("Azure STT stopped")

    def _on_recognizing(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        text = evt.result.text
        if text and self._loop:
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait,
                {"type": "interim", "text": text},
            )

    def _on_recognized(self, evt: speechsdk.SpeechRecognitionEventArgs) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and self._loop:
            text = evt.result.text
            if text:
                self._loop.call_soon_threadsafe(
                    self._queue.put_nowait,
                    {"type": "recognized", "text": text},
                )

    def _on_canceled(self, evt: speechsdk.SpeechRecognitionCanceledEventArgs) -> None:
        details = evt.cancellation_details
        if details.reason == speechsdk.CancellationReason.Error:
            logger.error("Azure STT error: %s", details.error_details)
