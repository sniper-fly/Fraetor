from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.intent_translation.domain.ports import ScreenshotCapturePort
    from src.shared.config.ports import SettingsRepositoryPort


class SegmentScreenshotPairer:
    """発話セグメントと画面スクリーンショットの対応付けを管理する状態機械。

    `on_speech_start`で撮影したスクリーンショットは`on_flush`で
    `produced_text=True`のときのみFIFOキューに積まれる。recognizedイベント
    が発行されないセグメント(認識結果が空)のスクリーンショットは捨てる。
    こうしないと、対応先のないスクリーンショットがキューに残り続け、
    以降の全セグメントの対応が1つずつずれる。
    """

    def __init__(
        self,
        *,
        screenshot_capture: ScreenshotCapturePort,
        settings_repository: SettingsRepositoryPort,
    ) -> None:
        self._capture = screenshot_capture
        self._settings_repository = settings_repository
        self._pending: bytes | None = None
        self._ready: deque[bytes | None] = deque()

    def on_speech_start(self) -> None:
        settings = self._settings_repository.get()
        if not settings.intent_translation_enabled:
            self._pending = None
            return
        self._pending = self._capture.capture(settings.screenshot_monitor_index)

    def on_flush(self, *, produced_text: bool) -> None:
        if produced_text:
            self._ready.append(self._pending)
        self._pending = None

    def pop_ready(self) -> bytes | None:
        return self._ready.popleft() if self._ready else None

    def reset(self) -> None:
        self._pending = None
        self._ready.clear()
