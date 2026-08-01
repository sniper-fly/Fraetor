from __future__ import annotations

import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

from src.stt_mai import MaiTranscribeClient


def _make_client(
    queue: asyncio.Queue[dict[str, str]] | None = None,
) -> tuple[MaiTranscribeClient, MagicMock]:
    """MaiTranscribeClient と SDK モックを返す。"""
    if queue is None:
        queue = asyncio.Queue()
    with patch("src.stt_mai.TranscriptionClient") as mock_client_cls:
        client = MaiTranscribeClient(queue)
    return client, mock_client_cls.return_value


class TestCapabilities:
    def test_streaming_false_post_processing_true(self) -> None:
        client, _ = _make_client()
        cap = client.capabilities
        assert cap.streaming is False
        assert cap.post_processing is True


class TestFeedAndBuild:
    async def test_feed_audio_accumulates_buffer(self) -> None:
        client, _ = _make_client()
        await client.start()

        client.feed_audio(b"\x01\x02\x03\x04")
        client.feed_audio(b"\x05\x06")

        wav = client._build_wav()
        assert wav, "WAV data should not be empty"
        # ヘッダ込みでも12バイトより大きいことだけ確認
        with wave.open(io.BytesIO(wav), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            frames = wf.readframes(wf.getnframes())
            assert frames == b"\x01\x02\x03\x04\x05\x06"

    async def test_start_clears_previous_buffer(self) -> None:
        client, _ = _make_client()
        client.feed_audio(b"\xff\xff")
        await client.start()
        assert client._build_wav() == b""


class TestStop:
    async def test_no_audio_skips_transcribe(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        await client.start()

        await client.stop()

        mock_sdk_client.transcribe.assert_not_called()
        assert queue.empty()

    async def test_invokes_transcribe_with_locale_and_model(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        result = MagicMock()
        result.combined_phrases = [MagicMock(text="認識結果テキスト")]
        mock_sdk_client.transcribe.return_value = result

        await client.start()
        client.feed_audio(b"\x00" * 32)
        await client.stop()

        mock_sdk_client.transcribe.assert_called_once()
        request = mock_sdk_client.transcribe.call_args.args[0]
        # enhancedMode.model で MAI モデルを指定 (REST 仕様準拠)
        assert request.definition.locales == ["ja"]
        assert request.definition.enhanced_mode["model"] == "mai-transcribe-1"
        assert request.definition.enhanced_mode["enabled"] is True

        event = queue.get_nowait()
        assert event == {"type": "recognized", "text": "認識結果テキスト"}

    async def test_empty_text_is_skipped(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        result = MagicMock()
        result.combined_phrases = [MagicMock(text="")]
        mock_sdk_client.transcribe.return_value = result

        await client.start()
        client.feed_audio(b"\x00" * 32)
        await client.stop()

        assert queue.empty()

    async def test_no_combined_phrases_is_skipped(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        result = MagicMock()
        result.combined_phrases = []
        mock_sdk_client.transcribe.return_value = result

        await client.start()
        client.feed_audio(b"\x00" * 32)
        await client.stop()

        assert queue.empty()

    async def test_transcribe_failure_does_not_raise(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        mock_sdk_client.transcribe.side_effect = RuntimeError("API error")

        await client.start()
        client.feed_audio(b"\x00" * 32)
        # 例外を呑んで処理を継続することを確認
        await client.stop()

        assert queue.empty()
