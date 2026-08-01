from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.transcript_history.domain.models import FinalizedSession


class HistoryRepositoryPort(ABC):
    """確定済みセッション履歴の永続化ポート。"""

    @abstractmethod
    def save(
        self, session: FinalizedSession, *, text_override: str | None = None
    ) -> None:
        """セッションを履歴に追加する。text_override指定時は保存テキストを上書きする。"""

    @abstractmethod
    def list_all(self) -> list[dict[str, object]]:
        """保存済みの履歴レコードを新しい順に返す。"""

    @abstractmethod
    def delete(self, session_id: str) -> bool:
        """指定IDのセッションを履歴から削除する。削除できた場合Trueを返す。"""


class ClipboardPort(ABC):
    """クリップボードへのコピーポート。"""

    @abstractmethod
    async def copy(self, text: str) -> None:
        """テキストをクリップボードにコピーする。"""
