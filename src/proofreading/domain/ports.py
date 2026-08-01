from __future__ import annotations

from abc import ABC, abstractmethod


class ProofreadingPort(ABC):
    """テキスト校正の抽象ポート。"""

    @abstractmethod
    async def proofread(self, text: str) -> str:
        """テキストを校正し、校正済みテキストを返す。"""
