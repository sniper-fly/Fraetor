from __future__ import annotations

import asyncio
import io
import wave
from unittest.mock import MagicMock, patch

from src.dictation.infrastructure.stt.mai_transcribe_client import MaiTranscribeClient

_SAMPLE_RATE = 16000


def _make_client(
    queue: asyncio.Queue[dict[str, str]] | None = None,
) -> tuple[MaiTranscribeClient, MagicMock]:
    """MaiTranscribeClient と SDK モックを返す。"""
    if queue is None:
        queue = asyncio.Queue()
    with patch(
        "src.dictation.infrastructure.stt.mai_transcribe_client.TranscriptionClient"
    ) as mock_client_cls:
        client = MaiTranscribeClient(
            queue,
            endpoint="https://mai.example/",
            api_key="test-key",
            locale="ja",
            model_name="mai-transcribe-1",
            timeout_sec=60,
            sample_rate=_SAMPLE_RATE,
        )
    return client, mock_client_cls.return_value


class TestCapabilities:
    def test_streaming_false_post_processing_true(self) -> None:
        client, _ = _make_client()
        cap = client.capabilities
        assert cap.streaming is False
        assert cap.post_processing is True


def _sent_frames(mock_sdk_client: MagicMock, call_index: int = 0) -> bytes:
    """指定回目の transcribe 呼び出しで送られた WAV の PCM 部分を取り出す。"""
    request = mock_sdk_client.transcribe.call_args_list[call_index].args[0]
    wav_bytes = request.audio[1].getvalue()
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        return wf.readframes(wf.getnframes())


def _stub_transcribe(mock_sdk_client: MagicMock, *texts: str) -> None:
    """transcribe が呼び出し順に指定テキストを返すようにする。"""
    results = []
    for text in texts:
        result = MagicMock()
        result.combined_phrases = [MagicMock(text=text)]
        results.append(result)
    mock_sdk_client.transcribe.side_effect = results


class TestFeedAndBuild:
    async def test_feed_audio_accumulates_buffer(self) -> None:
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "認識結果")
        await client.start()

        client.feed_audio(b"\x01\x02\x03\x04")
        client.feed_audio(b"\x05\x06")
        await client.stop()

        request = mock_sdk_client.transcribe.call_args.args[0]
        with wave.open(io.BytesIO(request.audio[1].getvalue()), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.readframes(wf.getnframes()) == b"\x01\x02\x03\x04\x05\x06"

    async def test_start_clears_previous_buffer(self) -> None:
        """start() は前セッションの残骸を送信対象から外す。"""
        client, mock_sdk_client = _make_client()
        client.feed_audio(b"\xff\xff")

        await client.start()
        await client.stop()

        mock_sdk_client.transcribe.assert_not_called()

    async def test_start_resets_sent_offset(self) -> None:
        """flush 済みのセッションを start() し直すと、新しい音声が先頭から送られる。

        オフセットを戻さないと、次セッションの音声が「既に送信済み」と
        判定されて丸ごと捨てられる。
        """
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "1回目", "2回目")
        await client.start()
        client.feed_audio(b"\x01\x02")
        await client.flush(trim_before_sample=None)

        await client.start()
        client.feed_audio(b"\x03\x04")
        await client.stop()

        assert _sent_frames(mock_sdk_client, 1) == b"\x03\x04"


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

    async def test_sends_only_unflushed_remainder(self) -> None:
        """flush 済みの区間は stop() で再送されない。"""
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "前半", "後半")
        await client.start()
        client.feed_audio(b"\x01\x02")
        await client.flush(trim_before_sample=None)

        client.feed_audio(b"\x03\x04")
        await client.stop()

        assert _sent_frames(mock_sdk_client, 1) == b"\x03\x04"

    async def test_no_remainder_after_flush_skips_transcribe(self) -> None:
        """flush 直後に新規音声がなければ stop() は送信しない。"""
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "全部")
        await client.start()
        client.feed_audio(b"\x01\x02")
        await client.flush(trim_before_sample=None)

        await client.stop()

        assert mock_sdk_client.transcribe.call_count == 1


class TestFlush:
    async def test_sends_pending_audio_and_queues_recognized(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        _stub_transcribe(mock_sdk_client, "セグメント1")
        await client.start()
        client.feed_audio(b"\x01\x02\x03\x04")

        await client.flush(trim_before_sample=None)

        assert _sent_frames(mock_sdk_client) == b"\x01\x02\x03\x04"
        assert queue.get_nowait() == {"type": "recognized", "text": "セグメント1"}

    async def test_offset_advances_across_multiple_cycles(self) -> None:
        """feed → flush を繰り返すと、各回で新規追記分だけが送られる。"""
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "1", "2", "3")
        await client.start()

        client.feed_audio(b"\x01\x02")
        await client.flush(trim_before_sample=None)
        client.feed_audio(b"\x03\x04")
        await client.flush(trim_before_sample=None)
        client.feed_audio(b"\x05\x06")
        await client.flush(trim_before_sample=None)

        assert [_sent_frames(mock_sdk_client, i) for i in range(3)] == [
            b"\x01\x02",
            b"\x03\x04",
            b"\x05\x06",
        ]

    async def test_trim_before_sample_drops_leading_silence(self) -> None:
        """発話開始位置より前 (前方無音) は送信対象から除外される。"""
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "発話")
        await client.start()
        # 4サンプル(8バイト)の無音の後に4サンプルの発話がある想定
        client.feed_audio(b"\x00" * 8 + b"\x11\x11\x22\x22\x33\x33\x44\x44")

        await client.flush(trim_before_sample=4)

        assert _sent_frames(mock_sdk_client) == b"\x11\x11\x22\x22\x33\x33\x44\x44"

    async def test_trim_before_sample_does_not_resend_flushed_audio(self) -> None:
        """送信済み位置より前を指す trim は無視される (再送を防ぐ)。

        発話が前の区間から続いていた場合、VAD の発話開始位置は既に送信済みの
        範囲を指す。これをそのまま採用すると同じ音声を二重に認識してしまう。
        """
        client, mock_sdk_client = _make_client()
        _stub_transcribe(mock_sdk_client, "1回目", "2回目")
        await client.start()
        client.feed_audio(b"\x01\x02\x03\x04")
        await client.flush(trim_before_sample=None)

        client.feed_audio(b"\x05\x06")
        await client.flush(trim_before_sample=0)

        assert _sent_frames(mock_sdk_client, 1) == b"\x05\x06"

    async def test_no_pending_audio_skips_transcribe(self) -> None:
        """送るものがなければ transcribe を呼ばない (無音区間の no-op ガード)。"""
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        await client.start()

        await client.flush(trim_before_sample=None)

        mock_sdk_client.transcribe.assert_not_called()
        assert queue.empty()

    async def test_trim_beyond_buffer_skips_transcribe(self) -> None:
        """trim 位置がバッファ末尾以降なら送信しない (切り出し結果が空)。"""
        client, mock_sdk_client = _make_client()
        await client.start()
        client.feed_audio(b"\x01\x02")

        await client.flush(trim_before_sample=100)

        mock_sdk_client.transcribe.assert_not_called()

    async def test_failure_does_not_raise_and_advances_offset(self) -> None:
        """送信失敗は伝播せず、その区間は諦める (次回に再送しない)。

        失敗分をオフセットに含めないと、以降の全 flush が失敗区間を先頭から
        含み続け、認識済みテキストが重複して追記される。
        """
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        mock_sdk_client.transcribe.side_effect = RuntimeError("API error")
        await client.start()
        client.feed_audio(b"\x01\x02")

        await client.flush(trim_before_sample=None)

        assert queue.empty()

        _stub_transcribe(mock_sdk_client, "2回目")
        client.feed_audio(b"\x03\x04")
        await client.flush(trim_before_sample=None)

        assert _sent_frames(mock_sdk_client, 1) == b"\x03\x04"

    async def test_empty_text_is_not_queued(self) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client, mock_sdk_client = _make_client(queue)
        _stub_transcribe(mock_sdk_client, "")
        await client.start()
        client.feed_audio(b"\x01\x02")

        await client.flush(trim_before_sample=None)

        assert queue.empty()
