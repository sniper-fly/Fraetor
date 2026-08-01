"""プラットフォームに応じた AudioCapturePort 実装の選択 (DIコンテナ用ファクトリ)。"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from src.dictation.infrastructure.audio.per_session_capture import (
    PerSessionStreamCapture,
)
from src.dictation.infrastructure.audio.persistent_capture import (
    PersistentStreamCapture,
)

if TYPE_CHECKING:
    from src.dictation.domain.ports import AudioCapturePort


def create_audio_capture(sample_rate: int) -> AudioCapturePort:
    """実行プラットフォームに適した AudioCapturePort を生成する。

    - macOS: CoreAudio の stop/close デッドロック回避のため常駐ストリーム方式
    - その他 (Linux): 録音中のみマイクを掴むセッション開閉方式
    """
    if sys.platform == "darwin":
        return PersistentStreamCapture(sample_rate)
    return PerSessionStreamCapture(sample_rate)
