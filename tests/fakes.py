"""テスト全体で共用するポート実装のフェイク。"""

from __future__ import annotations

from src.shared.config.dynamic_settings import DynamicSettings
from src.shared.config.ports import SettingsRepositoryPort


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
