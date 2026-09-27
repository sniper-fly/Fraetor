from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from src.dictation.infrastructure.stt.factory import create_stt_engine
from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient

if TYPE_CHECKING:
    from src.dictation.domain.events import SttEvent

_SAMPLE_RATE = 16000


def _create(
    *,
    locale: str = "ja",
    model_name: str = "MAI-Transcribe-2",
    transcribe_style: str = "verbatim",
    timeout_sec: float = 60,
    queue: asyncio.Queue[SttEvent] | None = None,
) -> tuple[MaiTranscribeClient, MagicMock]:
    with patch(
        "src.dictation.infrastructure.stt.mai_transcribe_client.TranscriptionClient"
    ) as mock_client_cls:
        engine = create_stt_engine(
            queue if queue is not None else asyncio.Queue(),
            endpoint="https://mai.example/",
            api_key="test-key",
            sample_rate=_SAMPLE_RATE,
            locale_fn=lambda: locale,
            model_name_fn=lambda: model_name,
            transcribe_style_fn=lambda: transcribe_style,
            timeout_sec_fn=lambda: timeout_sec,
        )
    assert isinstance(engine, MaiTranscribeClient)
    return engine, mock_client_cls


class TestCreateSttEngine:
    def test_creates_mai_transcribe_client(self) -> None:
        engine, _ = _create()

        assert isinstance(engine, MaiTranscribeClient)

    def test_passes_current_dynamic_values(self) -> None:
        engine, _ = _create(locale="en", transcribe_style="clean", timeout_sec=30)

        assert engine._locale == "en"
        assert engine._model_name == "MAI-Transcribe-2"
        assert engine._transcribe_style == "clean"
        assert engine._timeout_sec == 30

    def test_reads_values_at_each_call(self) -> None:
        """MAI 設定は生成時に読むため、生成のたびに渡された callable の
        時点の値が使われる。"""
        current_locale = "ja"
        engine, _ = _create(locale=current_locale)
        first_locale = engine._locale

        current_locale = "en"
        engine2, _ = _create(locale=current_locale)

        assert (first_locale, engine2._locale) == ("ja", "en")

    def test_passes_secrets_without_dynamic_settings(self) -> None:
        """エンドポイント/APIキーはシークレット由来で、動的設定を経由しない。"""
        _, mock_client_cls = _create()

        assert mock_client_cls.call_args.kwargs["endpoint"] == "https://mai.example/"

    def test_uses_given_event_queue(self) -> None:
        """セッションごとに渡されたキューをそのまま使う (キュー分離の前提)。"""
        queue: asyncio.Queue[SttEvent] = asyncio.Queue()

        engine, _ = _create(queue=queue)

        assert engine._queue is queue
