from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.proofreading.domain.ports import ProofreadingPort

logger = logging.getLogger(__name__)


class ProofreadTextUseCase:
    """テキスト校正ユースケース。校正器未設定/失敗/タイムアウト時は元テキストを返す。"""

    def __init__(
        self, proofreader: ProofreadingPort | None, *, timeout_sec: float
    ) -> None:
        self._proofreader = proofreader
        self._timeout_sec = timeout_sec

    async def execute(self, text: str) -> tuple[str, bool]:
        """校正済みテキストと、校正が行われたかを返す。"""
        if self._proofreader is None:
            return text, False
        try:
            result = await asyncio.wait_for(
                self._proofreader.proofread(text), timeout=self._timeout_sec
            )
        except Exception:
            logger.exception("Proofreading failed")
            return text, False
        return result, True
