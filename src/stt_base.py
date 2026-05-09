from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    import asyncio


class SttCapabilities(BaseModel):
    """STTエンジンの能力を表す。"""

    streaming: bool
    """録音中に interim イベントを発火するか。"""

    post_processing: bool
    """stop() でバッチ処理が走り、完了まで時間がかかるか。"""


class SttEngine(ABC):
    """音声認識エンジンの抽象基底クラス。

    feed_audio で 16kHz/16bit/mono の PCM バイトを受け取り、
    認識結果は stt_event_queue に
    {"type": "interim"|"recognized", "text": ...} を投入する。
    """

    def __init__(self, stt_event_queue: asyncio.Queue[dict[str, str]]) -> None:
        self._queue = stt_event_queue

    @property
    @abstractmethod
    def capabilities(self) -> SttCapabilities: ...

    @abstractmethod
    async def start(self) -> None:
        """認識を開始する。"""

    @abstractmethod
    def feed_audio(self, buffer: bytes) -> None:
        """PCM音声データを送る (16kHz/16bit/mono)。"""

    @abstractmethod
    async def stop(self) -> None:
        """認識を停止する。

        バッチ型エンジンの場合はここで処理を実行し、結果を queue に投入する。
        """
