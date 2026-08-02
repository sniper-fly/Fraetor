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
