from __future__ import annotations

from abc import ABC, abstractmethod


class ProcessShutdownerPort(ABC):
    """プロセス終了スケジューリングの抽象ポート。"""

    @abstractmethod
    def schedule(self, delay_sec: float) -> None:
        """delay_sec 秒後にプロセスを終了させる。"""
