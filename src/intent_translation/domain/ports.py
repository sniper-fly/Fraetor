from __future__ import annotations

from abc import ABC, abstractmethod


class ScreenshotCapturePort(ABC):
    """画面スクリーンショット撮影の抽象ポート。"""

    @abstractmethod
    def capture(self, monitor_index: int) -> bytes | None:
        """PNG形式のスクリーンショットを撮る。失敗時はNoneを返す(例外は伝播させない)。"""


class IntentTranslatorPort(ABC):
    """認識結果テキストと画面情報から依頼文への変換の抽象ポート。"""

    @abstractmethod
    async def translate(self, text: str, screenshot_png: bytes) -> str:
        """認識結果テキストと画面スクリーンショットから依頼文を生成する。"""
