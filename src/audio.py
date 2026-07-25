"""プラットフォームに応じた AudioCapture 実装の選択 (コンポジションルート用)。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from src.audio_per_session import PerSessionStreamCapture
from src.audio_persistent import PersistentStreamCapture

if TYPE_CHECKING:
    from src.audio_base import AudioCapture


def create_audio_capture() -> AudioCapture:
    """実行プラットフォームに適した AudioCapture を生成する。

    - macOS: CoreAudio の stop/close デッドロック回避のため常駐ストリーム方式
    - その他 (Linux): 録音中のみマイクを掴むセッション開閉方式
    """
    if sys.platform == "darwin":
        return PersistentStreamCapture()
    return PerSessionStreamCapture()
