from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from src.stt_stats.domain.models import SttLatencySample


class SttLatencyRepositoryPort(ABC):
    """STT応答時間の記録の永続化ポート。"""

    @abstractmethod
    def save(self, sample: SttLatencySample) -> None:
        """記録を1件追加する。"""

    @abstractmethod
    def list_since(self, since: datetime) -> list[SttLatencySample]:
        """`since` 以降の記録を古い順に返す。"""
