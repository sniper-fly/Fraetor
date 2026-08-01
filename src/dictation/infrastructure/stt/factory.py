"""STTエンジン選択のファクトリ (DIコンテナ用)。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient

if TYPE_CHECKING:
    import asyncio

    from src.dictation.domain.ports import SttEnginePort


def create_stt_engine(
    stt_event_queue: asyncio.Queue[dict[str, str]],
    *,
    endpoint: str,
    api_key: str,
    locale: str,
    model_name: str,
    timeout_sec: float,
    sample_rate: int,
) -> SttEnginePort:
    """設定に応じたSTTエンジンを生成する。

    現状は MAI Transcribe のみだが、将来エンジンが増えた場合はここで分岐する
    (design.md: プラットフォーム分岐がファクトリの1箇所のみであるのと同型)。
    """
    return MaiTranscribeClient(
        stt_event_queue,
        endpoint=endpoint,
        api_key=api_key,
        locale=locale,
        model_name=model_name,
        timeout_sec=timeout_sec,
        sample_rate=sample_rate,
    )
