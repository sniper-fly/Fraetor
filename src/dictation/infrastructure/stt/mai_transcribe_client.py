from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave

from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import (
    EnhancedModeProperties,
    TranscriptionContent,
    TranscriptionOptions,
)
from azure.core.credentials import AzureKeyCredential

from src.dictation.domain.ports import SttCapabilities, SttEnginePort

logger = logging.getLogger(__name__)

_CAPABILITIES = SttCapabilities(streaming=False, post_processing=True)
_PCM_SAMPLE_WIDTH_BYTES = 2  # 16-bit
_PCM_CHANNELS = 1


class MaiTranscribeClient(SttEnginePort):
    """MAI-Transcribe によるバッチ文字起こしクライアント。

    feed_audio で蓄積した PCM を、無音区切りごとの `flush()` と最終の `stop()`
    で WAV 化し、Azure Foundry の LLM Speech API へ送信する。結果は
    combined_phrases[0].text を recognized イベントとして送信1回ごとに
    queue へ投入する (1セッションで複数件になる)。

    セッション全体の生 PCM を `_buffer` に保持し続け、どこまで送ったかを
    `_sent_offset_bytes` で覚える方式を採る。「送信済みの分を捨てる」形に
    しないのは、無音区切りの直前で語頭が欠けた場合に前の区間へさかのぼって
    切り出せる余地を残すため。バッファは `stop()` で必ず解放され、1セッション
    上限 (10分/16kHz/16bit/mono ≒ 19MB) を超えて増えることはない。
    """

    def __init__(
        self,
        stt_event_queue: asyncio.Queue[dict[str, str]],
        *,
        endpoint: str,
        api_key: str,
        locale: str,
        model_name: str,
        transcribe_style: str,
        timeout_sec: float,
        sample_rate: int,
    ) -> None:
        super().__init__(stt_event_queue)
        self._buffer = bytearray()
        self._sent_offset_bytes = 0
        # feed_audio は sounddevice のコールバックスレッドから、flush/stop は
        # イベントループから呼ばれる。バッファとオフセットの整合を守るために
        # メモリ操作だけを排他する (WAV化・HTTP送信はロックの外)。
        self._lock = threading.Lock()
        self._client = TranscriptionClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key),
        )
        self._locale = locale
        self._model_name = model_name
        self._transcribe_style = transcribe_style
        self._timeout_sec = timeout_sec
        self._sample_rate = sample_rate

    @property
    def capabilities(self) -> SttCapabilities:
        return _CAPABILITIES

    async def start(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._sent_offset_bytes = 0
        logger.info("MAI Transcribe started (buffering)")

    def feed_audio(self, buffer: bytes) -> None:
        with self._lock:
            self._buffer.extend(buffer)

    async def flush(self, *, trim_before_sample: int | None) -> str:
        """未送信区間を1セグメントとして送信する。バッファは解放しない。"""
        wav_bytes = self._extract_pending_wav(trim_before_sample)
        if not wav_bytes:
            return ""
        text = await self._transcribe(wav_bytes, phase="flush")
        logger.info("MAI Transcribe flushed (chars=%d)", len(text or ""))
        return text

    async def stop(self) -> None:
        # 残っている未送信分をすべて最終セグメントとして送る。無音区切りが
        # 一度も発生しなかったセッションでは、これが唯一の送信になる。
        wav_bytes = self._extract_pending_wav(trim_before_sample=None)
        with self._lock:
            self._buffer.clear()
            self._sent_offset_bytes = 0
        if not wav_bytes:
            logger.info("MAI Transcribe stopped (no audio)")
            return
        text = await self._transcribe(wav_bytes, phase="stop")
        logger.info("MAI Transcribe stopped (chars=%d)", len(text or ""))

    async def _transcribe(self, wav_bytes: bytes, *, phase: str) -> str:
        """WAV を送信し、テキストが得られれば recognized イベントを投入する。

        失敗はログに記録して握り潰す (プラン: リトライなし、テキストは失う)。
        呼び出し元は録音・後続セグメントの処理を継続する。
        """
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(self._transcribe_sync, wav_bytes),
                timeout=self._timeout_sec,
            )
        except Exception:
            logger.exception("MAI Transcribe %s failed", phase)
            return ""
        if text:
            self._queue.put_nowait({"type": "recognized", "text": text})
        return text

    def _extract_pending_wav(self, trim_before_sample: int | None) -> bytes:
        """未送信区間を切り出して WAV 化し、送信済みオフセットを進める。

        `trim_before_sample` が未送信区間の途中を指す場合はそこまでの無音を
        捨てる。既に送信済みの位置より前を指す場合 (発話が前の区間で始まって
        いた場合) は再送しないよう送信済み位置を優先する。
        """
        with self._lock:
            start = self._sent_offset_bytes
            if trim_before_sample is not None:
                start = max(start, trim_before_sample * _PCM_SAMPLE_WIDTH_BYTES)
            pending = bytes(self._buffer[start:])
            self._sent_offset_bytes = len(self._buffer)
        if not pending:
            return b""
        return self._build_wav(pending)

    def _build_wav(self, pcm_bytes: bytes) -> bytes:
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(_PCM_CHANNELS)
            wf.setsampwidth(_PCM_SAMPLE_WIDTH_BYTES)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm_bytes)
        return bio.getvalue()

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        # SDK b4 では EnhancedModeProperties に model/modelOptions フィールドが
        # 公開されていないため、MutableMapping の __setitem__ 経由で REST 仕様
        # (enhancedMode.model, enhancedMode.modelOptions.transcribeStyle) を満たす。
        enhanced_mode = EnhancedModeProperties()
        enhanced_mode["enabled"] = True
        enhanced_mode["model"] = self._model_name
        enhanced_mode["modelOptions"] = {"transcribeStyle": self._transcribe_style}
        options = TranscriptionOptions(
            locales=[self._locale],
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
