from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.stt import AzureSttClient


@patch("src.stt.speechsdk")
class TestAzureSttClientInit:
    def test_configures_speech_config(self, mock_sdk: MagicMock) -> None:
        """design.md: Azure Speech Services (japaneast, ja-JP)"""
        AzureSttClient(asyncio.Queue())

        mock_sdk.SpeechConfig.assert_called_once_with(
            subscription="",
            region="japaneast",
            speech_recognition_language="ja-JP",
        )

    def test_sets_stable_partial_result_threshold(self, mock_sdk: MagicMock) -> None:
        """design.md: STABLE_PARTIAL_RESULT_THRESHOLD = 3"""
        AzureSttClient(asyncio.Queue())

        speech_config = mock_sdk.SpeechConfig.return_value
        speech_config.set_property.assert_called_once_with(
            mock_sdk.PropertyId.SpeechServiceResponse_StablePartialResultThreshold,
            "3",
        )

    def test_creates_push_stream_with_pcm16_mono_16khz(
        self, mock_sdk: MagicMock
    ) -> None:
        """design.md: sounddevice(PCM) 16kHz 16-bit mono"""
        AzureSttClient(asyncio.Queue())

        mock_sdk.audio.AudioStreamFormat.assert_called_once_with(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )

    def test_connects_event_handlers(self, mock_sdk: MagicMock) -> None:
        client = AzureSttClient(asyncio.Queue())

        recognizer = mock_sdk.SpeechRecognizer.return_value
        recognizer.recognizing.connect.assert_called_once_with(
            client._on_recognizing,
        )
        recognizer.recognized.connect.assert_called_once_with(
            client._on_recognized,
        )
        recognizer.canceled.connect.assert_called_once_with(
            client._on_canceled,
        )


@patch("src.stt.speechsdk")
class TestAzureSttClientEvents:
    async def test_recognizing_enqueues_interim(self, mock_sdk: MagicMock) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        client._loop = asyncio.get_running_loop()

        evt = MagicMock()
        evt.result.text = "テスト"
        client._on_recognizing(evt)

        await asyncio.sleep(0)
        assert queue.get_nowait() == {"type": "interim", "text": "テスト"}

    async def test_recognizing_ignores_empty_text(self, mock_sdk: MagicMock) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        client._loop = asyncio.get_running_loop()

        evt = MagicMock()
        evt.result.text = ""
        client._on_recognizing(evt)

        await asyncio.sleep(0)
        assert queue.empty()

    async def test_recognized_enqueues_recognized(self, mock_sdk: MagicMock) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        client._loop = asyncio.get_running_loop()

        evt = MagicMock()
        evt.result.reason = mock_sdk.ResultReason.RecognizedSpeech
        evt.result.text = "認識結果"
        client._on_recognized(evt)

        await asyncio.sleep(0)
        assert queue.get_nowait() == {
            "type": "recognized",
            "text": "認識結果",
        }

    async def test_recognized_ignores_no_match(self, mock_sdk: MagicMock) -> None:
        """NoMatch の場合はキューに入れない"""
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        client._loop = asyncio.get_running_loop()

        evt = MagicMock()
        evt.result.reason = mock_sdk.ResultReason.NoMatch
        client._on_recognized(evt)

        await asyncio.sleep(0)
        assert queue.empty()

    async def test_canceled_error_logs(self, mock_sdk: MagicMock) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)

        evt = MagicMock()
        evt.cancellation_details.reason = mock_sdk.CancellationReason.Error
        evt.cancellation_details.error_details = "auth failed"

        with patch("src.stt.logger") as mock_logger:
            client._on_canceled(evt)
            mock_logger.error.assert_called_once()

    async def test_events_ignored_when_loop_is_none(self, mock_sdk: MagicMock) -> None:
        """stop 後 (_loop=None) にイベントが来てもキューに入れない"""
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        assert client._loop is None

        evt = MagicMock()
        evt.result.text = "テスト"
        client._on_recognizing(evt)

        await asyncio.sleep(0)
        assert queue.empty()


@patch("src.stt.speechsdk")
class TestAzureSttClientLifecycle:
    async def test_start_begins_recognition(self, mock_sdk: MagicMock) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)

        await client.start()

        recognizer = mock_sdk.SpeechRecognizer.return_value
        recognizer.start_continuous_recognition_async.assert_called_once()
        assert client._loop is not None

    async def test_stop_closes_stream_and_stops_recognition(
        self, mock_sdk: MagicMock
    ) -> None:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = AzureSttClient(queue)
        await client.start()

        await client.stop()

        push_stream = mock_sdk.audio.PushAudioInputStream.return_value
        push_stream.close.assert_called_once()
        recognizer = mock_sdk.SpeechRecognizer.return_value
        recognizer.stop_continuous_recognition_async.assert_called_once()
        assert client._loop is None

    def test_write_audio_forwards_to_push_stream(self, mock_sdk: MagicMock) -> None:
        client = AzureSttClient(asyncio.Queue())
        audio_bytes = b"\x00\x01\x02\x03"

        client.write_audio(audio_bytes)

        push_stream = mock_sdk.audio.PushAudioInputStream.return_value
        push_stream.write.assert_called_once_with(audio_bytes)
