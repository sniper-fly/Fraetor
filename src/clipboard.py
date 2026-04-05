from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def copy_to_clipboard(text: str) -> None:
    """xclip でテキストをクリップボードにコピーする。"""
    proc = await asyncio.create_subprocess_exec(
        "xclip",
        "-selection",
        "clipboard",
        stdin=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate(input=text.encode("utf-8"))
    if proc.returncode != 0:
        msg = f"xclip failed (returncode={proc.returncode}): {stderr.decode()}"
        raise RuntimeError(msg)
    logger.info("Copied %d chars to clipboard", len(text))


async def paste() -> None:
    """xdotool key ctrl+v でアクティブウィンドウにペーストする。"""
    proc = await asyncio.create_subprocess_exec(
        "xdotool",
        "key",
        "ctrl+v",
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = f"xdotool failed (returncode={proc.returncode}): {stderr.decode()}"
        raise RuntimeError(msg)
    logger.info("Pasted to active window")


async def copy_and_paste(text: str) -> None:
    """テキストをクリップボードにコピーし、アクティブウィンドウにペーストする。

    空文字の場合はスキップする。
    """
    if not text:
        logger.debug("Empty text, skipping copy and paste")
        return
    await copy_to_clipboard(text)
    await paste()
