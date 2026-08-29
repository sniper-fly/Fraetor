from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class HerdrSessionInfo(BaseModel):
    pane_id: str
    label: str


class HerdrClientPort(ABC):
    @abstractmethod
    async def get_focused_pane(self) -> HerdrSessionInfo | None:
        """今前面に出ているペインの情報 (ID・タイトル) を取得する。

        取得できない場合は None を返す (例外を投げない)。
        """

    @abstractmethod
    async def list_sessions(self) -> list[HerdrSessionInfo]:
        """選択UI表示用のセッション一覧。取得できない場合は空リスト。"""

    @abstractmethod
    async def send_text(self, pane_id: str, text: str) -> bool:
        """テキストを投入する。成功/失敗を bool で返す (例外を投げない)。"""
