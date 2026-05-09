from __future__ import annotations

import asyncio
import logging

import pyperclip

logger = logging.getLogger(__name__)


async def copy_to_clipboard(text: str) -> None:
    """pyperclip でテキストをクリップボードにコピーする (Mac/Linux/Windows 対応)。"""
    try:
        await asyncio.to_thread(pyperclip.copy, text)
    except pyperclip.PyperclipException as e:
        msg = f"pyperclip failed: {e}"
        raise RuntimeError(msg) from e
    logger.info("Copied %d chars to clipboard", len(text))
