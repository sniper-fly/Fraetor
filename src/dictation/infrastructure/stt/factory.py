"""STTエンジン選択のファクトリ (DIコンテナ用)。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient

if TYPE_CHECKING:
    import asyncio

    from src.dictation.domain.ports import SttEnginePort
    from src.shared.config.ports import SettingsRepositoryPort


def create_stt_engine(
    stt_event_queue: asyncio.Queue[dict[str, str]],
    *,
    settings_repository: SettingsRepositoryPort,
    endpoint: str,
    api_key: str,
    sample_rate: int,
) -> SttEnginePort:
    """設定に応じたSTTエンジンを生成する。

    現状は MAI Transcribe のみだが、将来エンジンが増えた場合はここで分岐する
    (design.md: プラットフォーム分岐がファクトリの1箇所のみであるのと同型)。

    ロケール・モデル名・タイムアウトは生成時 (= セッション開始時) に
    `settings_repository` から読む。エンジンはセッションごとに作り直される
    ため、設定画面からの変更は次のセッションで反映される。
    """
    settings = settings_repository.get()
    return MaiTranscribeClient(
        stt_event_queue,
        endpoint=endpoint,
        api_key=api_key,
        locale=settings.mai_locale,
        model_name=settings.mai_model_name,
        transcribe_style=settings.mai_transcribe_style,
        timeout_sec=settings.mai_timeout_sec,
        sample_rate=sample_rate,
    )
