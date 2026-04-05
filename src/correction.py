from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING

from google import genai
from google.genai import types

from src.config import CORRECTION_PROMPT, GEMINI_API_KEY, GEMINI_MODEL

if TYPE_CHECKING:
    from google.genai.live import AsyncSession

logger = logging.getLogger(__name__)


class GeminiCorrectionClient:
    """Gemini Live API を使ったテキスト校正クライアント。

    セッション開始時に接続し、テキストを直列で送信して校正済みテキストを受信する。
    Live API のセッション内コンテキストにより、前のセグメントを踏まえた校正が可能。
    """

    def __init__(self) -> None:
        self._client = genai.Client(
            api_key=GEMINI_API_KEY,
            http_options=types.HttpOptions(api_version="v1alpha"),
        )
        self._session: AsyncSession | None = None
        self._exit_stack: AsyncExitStack | None = None

    async def connect(self) -> None:
        """Gemini Live API セッションに接続する。"""
        # WORKAROUND: gemini-3.1-flash-live-preview は
        # TEXT modality 未サポート (1011エラー)。
        # 修正され次第 AUDIO→TEXT に戻し、
        # output_audio_transcription を削除する。
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(
                parts=[types.Part(text=CORRECTION_PROMPT)]
            ),
        )
        self._exit_stack = AsyncExitStack()
        self._session = await self._exit_stack.enter_async_context(
            self._client.aio.live.connect(model=GEMINI_MODEL, config=config)
        )
        logger.info("Gemini Live API connected")

    async def correct(self, text: str) -> str:
        """テキストを送信し、校正済みテキストを返す。

        send_realtime_input でテキストを送信し、receive() で turn_complete まで
        レスポンスを収集する。
        """
        if not self._session:
            raise RuntimeError("Not connected to Gemini Live API")

        await self._session.send_realtime_input(text=text)

        corrected_parts: list[str] = []
        async for message in self._session.receive():
            sc = message.server_content
            if sc and sc.output_transcription and sc.output_transcription.text:
                corrected_parts.append(sc.output_transcription.text)

        return "".join(corrected_parts) if corrected_parts else text

    async def disconnect(self) -> None:
        """セッションを切断する。"""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
            self._session = None
            logger.info("Gemini Live API disconnected")
