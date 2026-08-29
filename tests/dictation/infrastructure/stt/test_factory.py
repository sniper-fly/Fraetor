from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.dictation.infrastructure.stt.factory import create_stt_engine
from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository

_SAMPLE_RATE = 16000


def _create(
    repo: InMemorySettingsRepository,
    queue: asyncio.Queue[dict[str, str]] | None = None,
) -> tuple[MaiTranscribeClient, MagicMock]:
    with patch(
        "src.dictation.infrastructure.stt.mai_transcribe_client.TranscriptionClient"
    ) as mock_client_cls:
        engine = create_stt_engine(
            queue if queue is not None else asyncio.Queue(),
            settings_repository=repo,
            endpoint="https://mai.example/",
            api_key="test-key",
            sample_rate=_SAMPLE_RATE,
        )
    assert isinstance(engine, MaiTranscribeClient)
    return engine, mock_client_cls


class TestCreateSttEngine:
    def test_creates_mai_transcribe_client(self) -> None:
        engine, _ = _create(InMemorySettingsRepository())

        assert isinstance(engine, MaiTranscribeClient)

    def test_passes_current_dynamic_values(self) -> None:
        repo = InMemorySettingsRepository(
            DynamicSettings(
                mai_locale="en", mai_model_name="other-model", mai_timeout_sec=30
            )
        )

        engine, _ = _create(repo)

        assert engine._locale == "en"
        assert engine._model_name == "other-model"
        assert engine._timeout_sec == 30

    def test_reads_values_at_each_call(self) -> None:
        """MAI 設定は生成時に読むため、更新後の生成には新しい値が使われる。"""
        repo = InMemorySettingsRepository(DynamicSettings(mai_locale="ja"))
        first, _ = _create(repo)

        repo.update(DynamicSettings(mai_locale="en"))
        second, _ = _create(repo)

        assert (first._locale, second._locale) == ("ja", "en")

    def test_passes_secrets_without_dynamic_settings(self) -> None:
        """エンドポイント/APIキーはシークレット由来で、動的設定を経由しない。"""
        _, mock_client_cls = _create(InMemorySettingsRepository())

        assert mock_client_cls.call_args.kwargs["endpoint"] == "https://mai.example/"

    def test_uses_given_event_queue(self) -> None:
        """セッションごとに渡されたキューをそのまま使う (キュー分離の前提)。"""
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()

        engine, _ = _create(InMemorySettingsRepository(), queue)

        assert engine._queue is queue
