"""テスト全体で共用するポート実装のフェイク。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.domain.ports import SessionFinalizationHookPort
from src.shared.config.dynamic_settings import DynamicSettings
from src.shared.config.ports import SettingsRepositoryPort

if TYPE_CHECKING:
    from datetime import datetime

    from src.dictation.domain.models import RecordingSession


class InMemorySettingsRepository(SettingsRepositoryPort):
    """ファイル I/O を伴わない `SettingsRepositoryPort` 実装。

    「`update()` した値が次回の `get()` から反映される」という永続化層の
    契約だけを満たす。JSONC の読み書き自体は
    `tests/shared/config/test_jsonc_settings_repository.py` で検証する。
    """

    def __init__(self, settings: DynamicSettings | None = None) -> None:
        self._current = settings if settings is not None else DynamicSettings()

    def get(self) -> DynamicSettings:
        return self._current

    def update(self, new_settings: DynamicSettings) -> None:
        self._current = new_settings


class NoOpSessionFinalizationHook(SessionFinalizationHookPort):
    """テスト用のno-op実装。呼び出し引数を記録するのみ。"""

    def __init__(self) -> None:
        self.calls: list[tuple[RecordingSession, datetime, bool]] = []

    async def on_session_finalized(
        self, session: RecordingSession, *, ended_at: datetime, timed_out: bool
    ) -> None:
        self.calls.append((session, ended_at, timed_out))
