from __future__ import annotations

import logging

import mss
import mss.tools

from src.intent_translation.domain.ports import ScreenshotCapturePort

logger = logging.getLogger(__name__)


class MssScreenshotCapturer(ScreenshotCapturePort):
    """`mss`ライブラリによる画面スクリーンショット撮影。

    プラットフォーム分岐(`sys.platform`によるdarwin/other分岐)は持たない。
    OS差は`mss`ライブラリ内部で吸収される単一実装とする(`pyperclip`と同じ方針)。
    """

    def capture(self, monitor_index: int) -> bytes | None:
        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                if not 0 <= monitor_index < len(monitors):
                    logger.warning(
                        "screenshot_monitor_index=%d が範囲外です", monitor_index
                    )
                    return None
                shot = sct.grab(monitors[monitor_index])
                return mss.tools.to_png(shot.rgb, shot.size)
        except Exception:
            logger.exception("Screenshot capture failed")
            return None
