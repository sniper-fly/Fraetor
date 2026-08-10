from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.shared.config.dynamic_settings import DynamicSettings


class SettingsRepositoryPort(ABC):
    @abstractmethod
    def get(self) -> DynamicSettings:
        """現在の動的設定値を返す。"""

    @abstractmethod
    def update(self, new_settings: DynamicSettings) -> None:
        """値を更新し、永続化する。"""
