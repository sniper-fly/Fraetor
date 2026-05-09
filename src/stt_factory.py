from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src import config
from src.stt_azure import AzureSttClient
from src.stt_mai import MaiTranscribeClient

if TYPE_CHECKING:
    import asyncio

    from src.stt_base import SttEngine

logger = logging.getLogger(__name__)


def create_stt_engine(
    queue: asyncio.Queue[dict[str, str]],
) -> SttEngine:
    """設定に基づいて STT エンジンを生成する。"""
    engine = config.STT_ENGINE
    logger.info("Creating STT engine: %s", engine)
    if engine == "azure":
        return AzureSttClient(queue)
    if engine == "mai":
        return MaiTranscribeClient(queue)
    msg = f"Unknown STT_ENGINE: {engine!r}"
    raise ValueError(msg)
