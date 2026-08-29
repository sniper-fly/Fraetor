from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.containers import Container
from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.application.recording_session_service import (
    RecordingSessionService,
)
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster
from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient
from src.shared.config.dynamic_settings import DynamicSettings
from src.transcript_history.application.finalize_session_use_case import (
    FinalizeSessionUseCase,
)
from src.transcript_history.infrastructure.jsonl_history_repository import (
    JsonlHistoryRepository,
)

if TYPE_CHECKING:
    import pytest


class TestContainer:
    def test_assembles_recording_session_service(self) -> None:
        container = Container()

        service = container.recording_session_service()

        assert isinstance(service, RecordingSessionService)

    def test_assembles_audio_pipeline_coordinator(self) -> None:
        container = Container()

        coordinator = container.audio_pipeline_coordinator()

        assert isinstance(coordinator, AudioPipelineCoordinator)

    def test_assembles_finalize_session_use_case(self) -> None:
        container = Container()

        use_case = container.finalize_session_use_case()

        assert isinstance(use_case, FinalizeSessionUseCase)

    def test_broadcaster_is_singleton(self) -> None:
        container = Container()

        assert container.broadcaster() is container.broadcaster()

    def test_broadcaster_is_sse_broadcaster(self) -> None:
        container = Container()

        assert isinstance(container.broadcaster(), SSEBroadcaster)

    def test_history_repository_uses_settings_history_dir(self) -> None:
        container = Container()

        repo = container.history_repository()

        assert isinstance(repo, JsonlHistoryRepository)

    def test_proofreader_is_none_without_vertex_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "FRAETOR_SSM_MAI_API_KEY",
            "FRAETOR_SSM_MAI_ENDPOINT",
            "FRAETOR_SSM_VERTEX_SA",
        ):
            monkeypatch.delenv(var, raising=False)
        container = Container()

        assert container.proofreader() is None

    def test_intent_translator_is_none_without_mai_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for var in (
            "FRAETOR_SSM_MAI_API_KEY",
            "FRAETOR_SSM_MAI_ENDPOINT",
            "FRAETOR_SSM_VERTEX_SA",
        ):
            monkeypatch.delenv(var, raising=False)
        container = Container()

        assert container.intent_translator() is None

    def test_audio_pipeline_coordinator_receives_intent_translation_hook(
        self,
    ) -> None:
        container = Container()

        coordinator = container.audio_pipeline_coordinator()

        assert (
            coordinator._segment_lifecycle_hook
            is container.intent_translation_dictation_adapter()
        )

    def test_segment_accumulator_receives_intent_translation_hook(self) -> None:
        container = Container()

        accumulator = container.segment_accumulator()

        assert (
            accumulator._text_transform
            is container.intent_translation_dictation_adapter()
        )

    def test_stt_engine_factory_creates_new_instance_each_call(self) -> None:
        """delegationで取得したFactoryを呼ぶたびに新規インスタンスを生成する。

        セッションごとに独立したイベントキューを渡せるよう、
        stt_event_queue は呼び出し時の引数として渡す。
        """
        container = Container()
        factory = container.stt_engine_factory()

        first = factory(asyncio.Queue())  # type: ignore[operator]
        second = factory(asyncio.Queue())  # type: ignore[operator]

        assert first is not second


class TestSettingsRepositoryWiring:
    def test_settings_repository_is_singleton(self) -> None:
        """全消費側が同じインスタンスを見る (更新が伝播する前提)。"""
        container = Container()

        assert container.settings_repository() is container.settings_repository()

    def test_settings_file_lives_beside_history(self) -> None:
        container = Container()
        settings = container.settings()

        container.settings_repository()

        assert (settings.history_dir / "settings.jsonc").exists()

    def test_stt_engine_factory_reads_settings_at_call_time(self) -> None:
        """DI 配線時ではなくエンジン生成時に MAI 設定を読む。"""
        container = Container()
        repo = container.settings_repository()
        factory = container.stt_engine_factory()

        repo.update(DynamicSettings(mai_locale="en"))
        engine = factory(asyncio.Queue())  # type: ignore[operator]

        assert isinstance(engine, MaiTranscribeClient)
        assert engine._locale == "en"

    def test_recording_session_service_receives_repository(self) -> None:
        container = Container()

        service = container.recording_session_service()

        assert service._settings_repository is container.settings_repository()

    def test_proofread_use_case_receives_repository(self) -> None:
        container = Container()

        use_case = container.proofread_text_use_case()

        assert use_case._settings_repository is container.settings_repository()

    def test_intent_translation_use_case_receives_repository(self) -> None:
        container = Container()

        use_case = container.intent_translation_use_case()

        assert use_case._settings_repository is container.settings_repository()

    def test_segment_screenshot_pairer_receives_repository(self) -> None:
        container = Container()

        pairer = container.segment_screenshot_pairer()

        assert pairer._settings_repository is container.settings_repository()

    def test_segment_silence_sec_is_read_at_call_time(self) -> None:
        """コーディネータは Singleton なので、閾値は callable 経由で都度読む。

        値を直接束縛すると起動時の値に固定され、設定変更が反映されない。
        """
        container = Container()
        repo = container.settings_repository()
        coordinator = container.audio_pipeline_coordinator()

        repo.update(DynamicSettings(segment_silence_sec=1.5))

        assert coordinator._segment_silence_sec_fn() == 1.5
