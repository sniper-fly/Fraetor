from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dependency_injector import containers, providers
from dictation import (
    STT_ENGINE_SPECS,
    AppState,
    AudioPipelineCoordinator,
    RecordingSessionService,
    SegmentAccumulator,
    SSEBroadcaster,
    SttCredentials,
    SttEventRelay,
    TranscriptionQueue,
    create_audio_capture,
    create_vad,
)

from src.intent_translation.application.dictation_hook_adapter import (
    IntentTranslationDictationAdapter,
)
from src.intent_translation.application.intent_translation_use_case import (
    IntentTranslationUseCase,
)
from src.intent_translation.application.segment_screenshot_pairer import (
    SegmentScreenshotPairer,
)
from src.intent_translation.infrastructure.azure_openai_intent_translator import (
    AzureOpenAIIntentTranslator,
)
from src.intent_translation.infrastructure.screenshot.mss_screenshot_capturer import (
    MssScreenshotCapturer,
)
from src.proofreading.application.proofread_text_use_case import ProofreadTextUseCase
from src.proofreading.infrastructure.vertex_gemini_proofreader import (
    VertexGeminiProofreader,
)
from src.shared.config.jsonc_settings_repository import JsoncSettingsRepository
from src.shared.config.secrets_loader import Secrets, load_secrets
from src.shared.config.settings import load_settings
from src.shared.herdr.socket_client import HerdrSocketClient
from src.shared.process.signal_process_shutdowner import ProcessShutdowner
from src.stt_stats.application.latency_hook_adapter import SttLatencyRecorder
from src.stt_stats.application.summarize_latency_use_case import (
    SummarizeLatencyUseCase,
)
from src.stt_stats.infrastructure.jsonl_latency_repository import (
    JsonlLatencyRepository,
)
from src.transcript_history.application.dictation_finalization_adapter import (
    DictationSessionFinalizationAdapter,
)
from src.transcript_history.application.finalize_session_use_case import (
    FinalizeSessionUseCase,
)
from src.transcript_history.application.pending_session_store import (
    PendingSessionStore,
)
from src.transcript_history.infrastructure.jsonl_history_repository import (
    JsonlHistoryRepository,
)
from src.transcript_history.infrastructure.pyperclip_clipboard import (
    PyperclipClipboard,
)

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable

    from dictation import SttEnginePort, SttEvent, SttLatencyHookPort
    from dictation.domain.ports import AudioCapturePort

    from src.shared.config.ports import SettingsRepositoryPort
    from src.shared.herdr.ports import HerdrClientPort

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


def _segment_silence_sec_fn(
    settings_repository: SettingsRepositoryPort,
) -> Callable[[], float]:
    """無音区切り閾値を都度読む callable を返す。

    `AudioPipelineCoordinator` は Singleton なので、値を直接渡すと起動時の
    値に固定されてしまう。セッション開始時に評価される callable を渡すことで
    「次のセッションから反映」を成立させる。
    """
    return lambda: settings_repository.get().segment_silence_sec


def _dynamic_float_fn(
    settings_repository: SettingsRepositoryPort, attr: str
) -> Callable[[], float]:
    """`DynamicSettings` の指定属性 (float) を都度読む callable を返す。

    `_segment_silence_sec_fn` と同じ「呼び出し時に評価する」パターンの
    汎用版。dictation ライブラリがFraetor固有の `DynamicSettings` を
    知らずに済むよう、`Callable[[], float]` に変換してから渡す。
    """
    return lambda: getattr(settings_repository.get(), attr)


def _stt_credentials(secrets: Secrets) -> SttCredentials:
    return SttCredentials(
        mai_endpoint=secrets.mai_endpoint,
        mai_api_key=secrets.mai_api_key,
        vertex_sa_info=secrets.vertex_sa_info,
        vertex_project=secrets.vertex_project,
    )


def _stt_settings_schemas() -> dict[str, dict[str, Any]]:
    """エンジンごとの設定モデルの JSON Schema (設定画面の入力欄の元)。"""
    return {
        name: spec.settings_model.model_json_schema()
        for name, spec in STT_ENGINE_SPECS.items()
    }


def _stt_engine_factory(
    *,
    settings_repository: SettingsRepositoryPort,
    credentials: SttCredentials,
    sample_rate: int,
    latency_hook: SttLatencyHookPort,
) -> Callable[[asyncio.Queue[SttEvent]], SttEnginePort]:
    """セッション開始ごとに、その時点で選択中のエンジンを生成する関数を返す。

    エンジン名と設定はどちらも呼び出し時に読む。設定画面で切り替えた内容は
    次のセッションから反映される。
    """

    def create(stt_event_queue: asyncio.Queue[SttEvent]) -> SttEnginePort:
        stt_settings = settings_repository.get().stt
        engine = stt_settings.engine
        return STT_ENGINE_SPECS[engine].create(
            stt_event_queue,
            credentials=credentials,
            sample_rate=sample_rate,
            settings_fn=lambda: getattr(settings_repository.get().stt, engine),
            latency_hook=latency_hook,
        )

    return create


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


def _create_intent_translator(
    *,
    mai_api_key: str,
    mai_endpoint: str,
    deployment: str,
    api_version: str,
    prompt: str,
) -> AzureOpenAIIntentTranslator | None:
    """MAI用シークレットを流用してAzure OpenAI互換クライアントを生成する。

    同一Azureリソースを STT (MaiTranscribeClient) とチャット補完 (意図翻訳)
    の両方で使うため、専用のシークレットは追加せず mai_api_key/mai_endpoint
    をそのまま使う。
    """
    if not mai_api_key or not mai_endpoint:
        return None
    return AzureOpenAIIntentTranslator(
        endpoint=mai_endpoint,
        api_key=mai_api_key,
        deployment=deployment,
        api_version=api_version,
        prompt=prompt,
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

    # 動的設定に依存する値 (使うエンジン/エンジンごとの設定/threshold) は
    # provider の引数として束縛せず、ファクトリ関数が呼び出し時に
    # settings_repository から読む。DI 配線時に値が固定されると設定画面の
    # 変更が反映されない。
    stt_credentials = providers.Singleton(
        _stt_credentials,
        secrets=secrets,
    )

    stt_settings_schemas = providers.Singleton(_stt_settings_schemas)

    stt_latency_repository = providers.Singleton(
        JsonlLatencyRepository, history_dir=settings.provided.history_dir
    )

    stt_latency_recorder = providers.Singleton(
        SttLatencyRecorder, repository=stt_latency_repository
    )

    summarize_latency_use_case = providers.Singleton(
        SummarizeLatencyUseCase, repository=stt_latency_repository
    )

    stt_engine_factory = providers.Callable(
        _stt_engine_factory,
        settings_repository=settings_repository,
        credentials=stt_credentials,
        sample_rate=settings.provided.stt_sample_rate,
        latency_hook=stt_latency_recorder,
    )

    vad_factory = providers.Factory(
        create_vad,
        sample_rate=settings.provided.stt_sample_rate,
        threshold_fn=providers.Callable(
            _dynamic_float_fn, settings_repository, "vad_threshold"
        ),
    ).provider

    screenshot_capture = providers.Singleton(MssScreenshotCapturer)

    segment_screenshot_pairer = providers.Singleton(
        SegmentScreenshotPairer,
        screenshot_capture=screenshot_capture,
        settings_repository=settings_repository,
    )

    intent_translator = providers.Singleton(
        _create_intent_translator,
        mai_api_key=secrets.provided.mai_api_key,
        mai_endpoint=secrets.provided.mai_endpoint,
        deployment=settings.provided.intent_translation_model_name,
        api_version=settings.provided.azure_openai_api_version,
        prompt=settings.provided.intent_translation_prompt,
    )

    intent_translation_use_case = providers.Singleton(
        IntentTranslationUseCase,
        translator=intent_translator,
        settings_repository=settings_repository,
    )

    intent_translation_dictation_adapter = providers.Singleton(
        IntentTranslationDictationAdapter,
        pairer=segment_screenshot_pairer,
        use_case=intent_translation_use_case,
    )

    audio_pipeline_coordinator = providers.Singleton(
        AudioPipelineCoordinator,
        audio_capture=audio_capture,
        stt_engine_factory=stt_engine_factory,
        vad_factory=vad_factory,
        segment_silence_sec_fn=providers.Callable(
            _segment_silence_sec_fn, settings_repository=settings_repository
        ),
        segment_lifecycle_hook=intent_translation_dictation_adapter,
    )

    segment_accumulator = providers.Singleton(
        SegmentAccumulator,
        broadcaster=broadcaster,
        text_transform=intent_translation_dictation_adapter,
    )

    stt_event_relay = providers.Singleton(
        SttEventRelay, app_state=app_state, accumulator=segment_accumulator
    )

    pending_session_store = providers.Singleton(PendingSessionStore)

    dictation_finalization_adapter = providers.Singleton(
        DictationSessionFinalizationAdapter, pending_store=pending_session_store
    )

    transcription_queue = providers.Singleton(
        TranscriptionQueue,
        app_state=app_state,
        accumulator=segment_accumulator,
        finalization_hook=dictation_finalization_adapter,
    )

    recording_session_service = providers.Singleton(
        RecordingSessionService,
        app_state=app_state,
        audio_pipeline=audio_pipeline_coordinator,
        event_relay=stt_event_relay,
        transcription_queue=transcription_queue,
        max_session_duration_sec_fn=providers.Callable(
            _dynamic_float_fn, settings_repository, "max_session_duration_sec"
        ),
        silence_timeout_sec_fn=providers.Callable(
            _dynamic_float_fn, settings_repository, "silence_timeout_sec"
        ),
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

    herdr_client: providers.Provider[HerdrClientPort] = providers.Singleton(
        HerdrSocketClient
    )
