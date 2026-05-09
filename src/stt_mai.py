from __future__ import annotations

import asyncio
import io
import logging
import wave

from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import (
    EnhancedModeProperties,
    TranscriptionContent,
    TranscriptionOptions,
)
from azure.core.credentials import AzureKeyCredential

from src.config import (
    MAI_API_KEY,
    MAI_ENDPOINT,
    MAI_LOCALE,
    MAI_MODEL_NAME,
    MAI_TIMEOUT_SEC,
    STT_SAMPLE_RATE,
)
from src.stt_base import SttCapabilities, SttEngine

logger = logging.getLogger(__name__)

_CAPABILITIES = SttCapabilities(streaming=False, post_processing=True)
_PCM_SAMPLE_WIDTH_BYTES = 2  # 16-bit
_PCM_CHANNELS = 1


class MaiTranscribeClient(SttEngine):
    """MAI-Transcribe-1 によるバッチ文字起こしクライアント。

    feed_audio で蓄積した PCM を stop() 時に WAV 化し、
    Azure Foundry の LLM Speech API へ一括送信する。
    結果は combined_phrases[0].text を recognized イベントとして
    queue に 1 件だけ投入する。
    """

    def __init__(
        self,
        stt_event_queue: asyncio.Queue[dict[str, str]],
    ) -> None:
        super().__init__(stt_event_queue)
        self._buffer = bytearray()
        self._client = TranscriptionClient(
            endpoint=MAI_ENDPOINT,
            credential=AzureKeyCredential(MAI_API_KEY),
        )

    @property
    def capabilities(self) -> SttCapabilities:
        return _CAPABILITIES

    async def start(self) -> None:
        self._buffer.clear()
        logger.info("MAI Transcribe started (buffering)")

    def feed_audio(self, buffer: bytes) -> None:
        self._buffer.extend(buffer)

    async def stop(self) -> None:
        wav_bytes = self._build_wav()
        self._buffer.clear()
        if not wav_bytes:
            logger.info("MAI Transcribe stopped (no audio)")
            return
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, wav_bytes),
                timeout=MAI_TIMEOUT_SEC,
            )
        except Exception:
            logger.exception("MAI Transcribe failed")
            return
        if text:
            self._queue.put_nowait({"type": "recognized", "text": text})
        logger.info("MAI Transcribe stopped (chars=%d)", len(text or ""))

    def _build_wav(self) -> bytes:
        if not self._buffer:
            return b""
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(_PCM_CHANNELS)
            wf.setsampwidth(_PCM_SAMPLE_WIDTH_BYTES)
            wf.setframerate(STT_SAMPLE_RATE)
            wf.writeframes(bytes(self._buffer))
        return bio.getvalue()

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        # SDK b4 では EnhancedModeProperties に model フィールドが公開されていないため、
        # MutableMapping の __setitem__ 経由で REST 仕様 (enhancedMode.model) を満たす。
        enhanced_mode = EnhancedModeProperties()
        enhanced_mode["enabled"] = True
        enhanced_mode["model"] = MAI_MODEL_NAME
        options = TranscriptionOptions(
            locales=[MAI_LOCALE],
            enhanced_mode=enhanced_mode,
        )
        request = TranscriptionContent(
            definition=options,
            audio=("audio.wav", io.BytesIO(wav_bytes), "audio/wav"),
        )
        result = self._client.transcribe(request)
        if result.combined_phrases:
            text = result.combined_phrases[0].text
            return text or ""
        return ""
