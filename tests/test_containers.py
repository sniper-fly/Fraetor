from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from unittest.mock import patch

import pytest
import responses
from dependency_injector import providers
from dictation import GeminiSettings, MaiSettings, SSEBroadcaster
from dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from dictation.application.recording_session_service import (
    RecordingSessionService,
)

from src.containers import Container, _dynamic_float_fn
from src.shared.config.dynamic_settings import DynamicSettings, SttSettings
from src.shared.config.secrets_loader import Secrets
from src.transcript_history.application.finalize_session_use_case import (
    FinalizeSessionUseCase,
)
from src.transcript_history.infrastructure.jsonl_history_repository import (
    JsonlHistoryRepository,
)
from tests.fakes import InMemorySettingsRepository

_DEFINITION_PART = re.compile(
    rb'name="definition"[^\r]*\r\n(?:[^\r]+\r\n)*\r\n(.*?)\r\n--', re.DOTALL
)


_MAI_SECRETS = Secrets(
    mai_api_key="test-key",
    mai_endpoint="https://mai.example/",
    vertex_sa_info={},
    vertex_project="",
)


def _extract_multipart_definition(body: bytes) -> dict[str, Any]:
    """multipart リクエストから definition (JSON) パートを取り出す。"""
    match = _DEFINITION_PART.search(body)
    assert match is not None, "リクエストに definition パートが含まれていない"
    parsed: dict[str, Any] = json.loads(match.group(1))
    return parsed


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
        container.secrets.override(providers.Object(_MAI_SECRETS))
        factory = container.stt_engine_factory()

        first = factory(asyncio.Queue())
        second = factory(asyncio.Queue())

        assert first is not second

    def test_missing_credentials_for_selected_engine_raise_clear_error(self) -> None:
        """資格情報が無いエンジンを選んだ場合、セッション開始時に原因が分かる。"""
        container = Container()
        container.secrets.override(providers.Object(_MAI_SECRETS))
        container.settings_repository().update(
            DynamicSettings(stt=SttSettings(engine="gemini"))
        )
        factory = container.stt_engine_factory()

        with pytest.raises(ValueError, match="Vertex AI"):
            factory(asyncio.Queue())

    def test_engine_selection_is_read_at_each_session(self) -> None:
        """`stt.engine` を切り替えると、次の生成から別エンジンの送信先になる。

        内部属性ではなく、`genai.Client` に渡る Vertex の project / location で
        配線を確認する。
        """
        container = Container()
        container.secrets.override(
            providers.Object(
                Secrets(
                    mai_api_key="k",
                    mai_endpoint="https://mai.example/",
                    vertex_sa_info={"type": "service_account"},
                    vertex_project="my-project",
                )
            )
        )
        repo = container.settings_repository()
        factory = container.stt_engine_factory()
        repo.update(
            DynamicSettings(
                stt=SttSettings(engine="gemini", gemini=GeminiSettings(location="eu"))
            )
        )

        with (
            patch(
                "dictation.infrastructure.stt.gemini_transcribe_client.genai.Client"
            ) as client_cls,
            patch(
                "dictation.infrastructure.stt.gemini_transcribe_client.service_account"
            ),
        ):
            factory(asyncio.Queue())

        kwargs = client_cls.call_args.kwargs
        assert kwargs["project"] == "my-project"
        assert kwargs["location"] == "eu"
        assert kwargs["vertexai"] is True


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

    async def test_stt_engine_factory_wires_settings_into_request(self) -> None:
        """動的設定が、エンジン生成時に実際のリクエスト内容へ配線される。

        DI 配線時ではなくエンジン生成時に読むこと (設定画面の変更が次の
        セッションから反映されること) と、設定の項目名の取り違えがないことを、
        実際に送信される HTTP リクエストの内容で確認する。
        """
        container = Container()
        container.secrets.override(
            providers.Object(
                Secrets(
                    mai_api_key="test-key",
                    mai_endpoint="https://mai.example/",
                    vertex_sa_info={},
                    vertex_project="",
                )
            )
        )
        factory = container.stt_engine_factory()

        container.settings_repository().update(
            DynamicSettings(
                stt=SttSettings(
                    mai=MaiSettings(locale="en", transcribe_style="verbatim")
                )
            )
        )
        engine = factory(asyncio.Queue())
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                re.compile(r".*/speechtotext/transcriptions:transcribe.*"),
                status=200,
                json={"combinedPhrases": [{"text": "x"}]},
            )
            await engine.start()
            engine.feed_audio(b"\x00\x00" * 1600)
            await engine.stop()
            body = rsps.calls[0].request.body

        assert isinstance(body, bytes)
        definition = _extract_multipart_definition(body)
        assert definition["locales"] == ["en"]
        assert definition["enhancedMode"]["model"] == "MAI-Transcribe-2"
        assert definition["enhancedMode"]["modelOptions"] == {
            "transcribeStyle": "verbatim"
        }

    def test_recording_session_service_receives_repository(self) -> None:
        container = Container()
        repo = container.settings_repository()
        service = container.recording_session_service()

        repo.update(DynamicSettings(max_session_duration_sec=42.0))

        assert service._max_session_duration_sec_fn() == 42.0

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


class TestDynamicSettingsFn:
    def test_dynamic_float_fn_reads_attribute_at_call_time(self) -> None:
        repo = InMemorySettingsRepository(DynamicSettings(vad_threshold=0.3))
        fn = _dynamic_float_fn(repo, "vad_threshold")

        repo.update(DynamicSettings(vad_threshold=0.9))

        assert fn() == 0.9


class TestTranscriptionQueueWiring:
    def test_receives_dictation_finalization_adapter(self) -> None:
        container = Container()

        queue = container.transcription_queue()

        assert queue._finalization_hook is container.dictation_finalization_adapter()

    def test_dictation_finalization_adapter_shares_pending_session_store(
        self,
    ) -> None:
        container = Container()

        adapter = container.dictation_finalization_adapter()

        assert adapter._pending_store is container.pending_session_store()
