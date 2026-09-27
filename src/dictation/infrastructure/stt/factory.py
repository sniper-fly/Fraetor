"""STTエンジン選択のファクトリ (DIコンテナ用)。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

    from src.dictation.domain.events import SttEvent
    from src.dictation.domain.ports import SttEnginePort


def create_stt_engine(
    stt_event_queue: asyncio.Queue[SttEvent],
    *,
    endpoint: str,
    api_key: str,
    sample_rate: int,
    locale_fn: Callable[[], str],
    model_name_fn: Callable[[], str],
    transcribe_style_fn: Callable[[], str],
    timeout_sec_fn: Callable[[], float],
) -> SttEnginePort:
    """設定に応じたSTTエンジンを生成する。

    現状は MAI Transcribe のみだが、将来エンジンが増えた場合はここで分岐する
    (design.md: プラットフォーム分岐がファクトリの1箇所のみであるのと同型)。

    ロケール・モデル名・タイムアウトは生成時 (= セッション開始時) に
    各 `Callable` から読む。エンジンはセッションごとに作り直されるため、
    設定画面からの変更は次のセッションで反映される。
    """
    return MaiTranscribeClient(
        stt_event_queue,
        endpoint=endpoint,
        api_key=api_key,
        locale=locale_fn(),
        model_name=model_name_fn(),
        transcribe_style=transcribe_style_fn(),
        timeout_sec=timeout_sec_fn(),
        sample_rate=sample_rate,
    )
