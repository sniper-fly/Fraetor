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
