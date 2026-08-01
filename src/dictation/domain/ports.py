from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable


class AudioCapturePort(ABC):
    """マイク音声キャプチャの抽象ポート。

    PCM データ (16kHz/16-bit/mono) をシンクに渡す。ストリームの
    ライフサイクル戦略 (常駐/セッション毎開閉) は実装側の詳細。
    """

    @abstractmethod
    async def start_recording(self, sink: Callable[[bytes], object]) -> None:
        """シンクを設定して録音を開始する。"""

    @abstractmethod
    async def stop_recording(self) -> None:
        """録音を停止する。ストリームの扱いは実装のライフサイクル戦略に従う。"""


class SttCapabilities(BaseModel):
    """STTエンジンの能力を表す。"""

    streaming: bool
    """録音中に interim イベントを発火するか。"""

    post_processing: bool
    """stop() でバッチ処理が走り、完了まで時間がかかるか。"""


class SttEnginePort(ABC):
    """音声認識エンジンの抽象ポート。

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


class SpeechActivityDetectorPort(ABC):
    """発話区間検出の抽象ポート。"""

    @property
    @abstractmethod
    def last_speech_time(self) -> float:
        """最後に発話を検知した時刻 (time.monotonic())。"""

    @abstractmethod
    def feed(self, pcm_bytes: bytes) -> None:
        """PCM (16kHz/16bit/mono) を受け取り、発話区間を検出する。"""


class EventBroadcasterPort(ABC):
    """SSE配信の抽象ポート。"""

    @abstractmethod
    def subscribe(self) -> asyncio.Queue[dict[str, str]]:
        """新規購読者のキューを登録して返す。"""

    @abstractmethod
    def unsubscribe(self, queue: asyncio.Queue[dict[str, str]]) -> None:
        """購読者のキューを解除する。"""

    @abstractmethod
    async def broadcast(self, event: str, data: Any) -> None:
        """全購読者にイベントを配信する。"""
