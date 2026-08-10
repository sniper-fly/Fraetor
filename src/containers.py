from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from dependency_injector import containers, providers

from src.dictation.application.app_state import AppState
from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.application.recording_session_service import (
    RecordingSessionService,
)
from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.application.stt_event_relay import SttEventRelay
from src.dictation.application.transcription_queue import TranscriptionQueue
from src.dictation.infrastructure.audio.factory import create_audio_capture
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster
from src.dictation.infrastructure.stt.factory import create_stt_engine
from src.dictation.infrastructure.vad.factory import create_vad
from src.proofreading.application.proofread_text_use_case import ProofreadTextUseCase
from src.proofreading.infrastructure.vertex_gemini_proofreader import (
    VertexGeminiProofreader,
)
from src.shared.config.jsonc_settings_repository import JsoncSettingsRepository
from src.shared.config.secrets_loader import Secrets, load_secrets
from src.shared.config.settings import load_settings
from src.shared.process.signal_process_shutdowner import ProcessShutdowner
from src.transcript_history.application.finalize_session_use_case import (
    FinalizeSessionUseCase,
)
from src.transcript_history.infrastructure.jsonl_history_repository import (
    JsonlHistoryRepository,
)
from src.transcript_history.infrastructure.pyperclip_clipboard import (
    PyperclipClipboard,
)

if TYPE_CHECKING:
    from src.dictation.domain.ports import AudioCapturePort

logger = logging.getLogger(__name__)


def _load_secrets_or_empty() -> Secrets:
    """シークレット取得に失敗した場合は空の Secrets にフォールバックする。

    未設定環境 (ローカル開発、テスト) でもアプリ自体は起動できるようにし、
    実際に MAI/Vertex を使う操作でのみエラーが顕在化する。
    """
    try:
        return load_secrets()
    except RuntimeError:
        logger.warning("シークレットの取得に失敗しました。空値で起動します。")
        return Secrets(
            mai_api_key="", mai_endpoint="", vertex_sa_info={}, vertex_project=""
        )


def _settings_file_path(history_dir: Path) -> Path:
    """動的設定ファイルのパスを組み立てる。

    履歴 (`history.jsonl`) と同じアプリ専用ディレクトリ配下に置く。
    E2E テストが `FRAETOR_HISTORY_DIR` を差し替えると設定ファイルも
    一緒に隔離されるため、テスト間で設定が漏れない。
    """
    return history_dir / "settings.jsonc"


def _create_proofreader(
    *,
    vertex_sa_info: dict[str, object],
    vertex_project: str,
    vertex_location: str,
    gemini_model: str,
    proofread_prompt: str,
) -> VertexGeminiProofreader | None:
    if not vertex_sa_info:
        return None
    return VertexGeminiProofreader(
        sa_info=vertex_sa_info,
        project=vertex_project,
        location=vertex_location,
        model=gemini_model,
        prompt=proofread_prompt,
    )


class Container(containers.DeclarativeContainer):
    """アプリケーション全体のDIコンテナ。

    Presentation層はここから取得した具象/ポートインスタンスを `app.state` に
    格納して使う。FastAPI の `@inject`/`Provide[]` wiring は mypy strict との
    相性問題があるため使わない。
    """

    settings = providers.Singleton(load_settings)
    secrets = providers.Singleton(_load_secrets_or_empty)

    settings_repository = providers.Singleton(
        JsoncSettingsRepository,
        path=providers.Callable(
            _settings_file_path, history_dir=settings.provided.history_dir
        ),
    )

    templates_dir = providers.Object(Path(__file__).parent / "templates")

    audio_capture: providers.Provider[AudioCapturePort] = providers.Singleton(
        create_audio_capture,
        sample_rate=settings.provided.stt_sample_rate,
    )

    broadcaster = providers.Singleton(SSEBroadcaster)

    app_state = providers.Singleton(AppState, broadcaster=broadcaster)

    # 動的設定に依存する値 (locale/model/timeout/threshold) は provider の
    # 引数として束縛せず、ファクトリ関数が呼び出し時に settings_repository
    # から読む。DI 配線時に値が固定されると設定画面の変更が反映されない。
    stt_engine_factory = providers.Factory(
        create_stt_engine,
        settings_repository=settings_repository,
        endpoint=secrets.provided.mai_endpoint,
        api_key=secrets.provided.mai_api_key,
        sample_rate=settings.provided.stt_sample_rate,
    ).provider

    vad_factory = providers.Factory(
        create_vad,
        settings_repository=settings_repository,
        sample_rate=settings.provided.stt_sample_rate,
    ).provider

    audio_pipeline_coordinator = providers.Singleton(
        AudioPipelineCoordinator,
        audio_capture=audio_capture,
        stt_engine_factory=stt_engine_factory,
        vad_factory=vad_factory,
    )

    segment_accumulator = providers.Singleton(
        SegmentAccumulator, broadcaster=broadcaster
    )

    stt_event_relay = providers.Singleton(
        SttEventRelay, app_state=app_state, accumulator=segment_accumulator
    )

    transcription_queue = providers.Singleton(
        TranscriptionQueue, app_state=app_state, accumulator=segment_accumulator
    )

    recording_session_service = providers.Singleton(
        RecordingSessionService,
        app_state=app_state,
        audio_pipeline=audio_pipeline_coordinator,
        event_relay=stt_event_relay,
        transcription_queue=transcription_queue,
        settings_repository=settings_repository,
    )

    history_repository = providers.Singleton(
        JsonlHistoryRepository,
        history_dir=settings.provided.history_dir,
    )

    clipboard = providers.Singleton(PyperclipClipboard)

    finalize_session_use_case = providers.Singleton(
        FinalizeSessionUseCase,
        clipboard=clipboard,
        history_repository=history_repository,
    )

    proofreader = providers.Singleton(
        _create_proofreader,
        vertex_sa_info=secrets.provided.vertex_sa_info,
        vertex_project=secrets.provided.vertex_project,
        vertex_location=settings.provided.vertex_location,
        gemini_model=settings.provided.gemini_model,
        proofread_prompt=settings.provided.proofread_prompt,
    )

    proofread_text_use_case = providers.Singleton(
        ProofreadTextUseCase,
        proofreader=proofreader,
        settings_repository=settings_repository,
    )

    shutdowner = providers.Singleton(ProcessShutdowner)
