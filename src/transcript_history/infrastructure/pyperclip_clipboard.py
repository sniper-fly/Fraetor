from __future__ import annotations

import asyncio
import logging

import pyperclip

from src.transcript_history.domain.ports import ClipboardPort

logger = logging.getLogger(__name__)


class PyperclipClipboard(ClipboardPort):
    """pyperclip によるクリップボードコピー (Mac/Linux/Windows 対応)。"""

    async def copy(self, text: str) -> None:
        try:
            await asyncio.to_thread(pyperclip.copy, text)
        except pyperclip.PyperclipException as e:
            msg = f"pyperclip failed: {e}"
            raise RuntimeError(msg) from e
        logger.info("Copied %d chars to clipboard", len(text))
