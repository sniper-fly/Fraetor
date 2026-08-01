"""Azure MAI Transcribe との実HTTPスタック経由の通信を検証するE2Eテスト。

正常系は実クラウド通信を許容する (低頻度実行のため)。異常系は
`responses` で `requests` ライブラリレベルの応答を差し替える。
`azure-ai-transcription` SDK は内部で `httpx` ではなく `requests` ベースの
`RequestsTransport` を使うため、`respx` (httpx専用) ではモックできない。

`src.stt_mai` は `src.config` の値をインポート時に束縛するため、各テストは
`init_secrets()` 実行後に `MaiTranscribeClient` を遅延インポートする
(モジュールトップレベルで先にインポートすると空文字列の設定値で
束縛されてしまう)。
"""

from __future__ import annotations

import asyncio
import re
import time
import wave
from pathlib import Path
from unittest.mock import patch

import responses

from src.config import init_secrets

_TRANSCRIBE_URL_PATTERN = re.compile(r".*/speechtotext/transcriptions:transcribe.*")
_SILENCE_PCM = b"\x00\x00" * 1600  # 0.1秒分の無音 (16kHz/16bit/mono)
_AUDIO_DIR = Path(__file__).parent / "fixtures" / "audio"


class TestRealCloudCommunication:
    async def test_normal_speech_is_transcribed_via_real_api(self) -> None:
        """正常系: 実クラウド通信で音声を送信し、認識結果が空でなく返る"""
        init_secrets()
        from src.stt_mai import MaiTranscribeClient  # noqa: PLC0415

        wav_path = _AUDIO_DIR / "01_normal_speech.wav"
        with wave.open(str(wav_path), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())

        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
        client = MaiTranscribeClient(queue)
        await client.start()
        client.feed_audio(pcm)
        await client.stop()

        assert not queue.empty(), "実クラウド通信でrecognizedイベントが届かなかった"
        event = queue.get_nowait()
        assert event["type"] == "recognized"
        assert event["text"], "認識結果テキストが空だった"


class TestErrorResponses:
    async def test_unauthorized_response_is_swallowed(self) -> None:
        """異常系: 401応答 → stop()が例外を握り潰し、recognizedが来ない"""
        init_secrets()
        from src.stt_mai import MaiTranscribeClient  # noqa: PLC0415

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                _TRANSCRIBE_URL_PATTERN,
                status=401,
                json={"error": "unauthorized"},
            )
            queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            client = MaiTranscribeClient(queue)
            await client.start()
            client.feed_audio(_SILENCE_PCM)
            await client.stop()

        assert queue.empty()

    async def test_rate_limited_response_is_swallowed(self) -> None:
        """異常系: 429応答 → stop()が例外を握り潰し、recognizedが来ない"""
        init_secrets()
        from src.stt_mai import MaiTranscribeClient  # noqa: PLC0415

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                _TRANSCRIBE_URL_PATTERN,
                status=429,
                json={"error": "too many requests"},
            )
            queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            client = MaiTranscribeClient(queue)
            await client.start()
            client.feed_audio(_SILENCE_PCM)
            await client.stop()

        assert queue.empty()

    async def test_server_error_response_is_swallowed(self) -> None:
        """異常系: 5xx応答 → stop()が例外を握り潰し、recognizedが来ない"""
        init_secrets()
        from src.stt_mai import MaiTranscribeClient  # noqa: PLC0415

        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                _TRANSCRIBE_URL_PATTERN,
                status=503,
                json={"error": "service unavailable"},
            )
            queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            client = MaiTranscribeClient(queue)
            await client.start()
            client.feed_audio(_SILENCE_PCM)
            await client.stop()

        assert queue.empty()

    async def test_timeout_is_swallowed(self) -> None:
        """異常系: MAI_TIMEOUT_SEC超過 → タイムアウトが握り潰され、recognizedが来ない"""
        init_secrets()
        from src.stt_mai import MaiTranscribeClient  # noqa: PLC0415

        def _slow_response(
            request: object,
        ) -> tuple[int, dict[str, str], str]:
            time.sleep(0.5)
            return (200, {}, "{}")

        with (
            responses.RequestsMock(assert_all_requests_are_fired=False) as rsps,
            patch("src.stt_mai.MAI_TIMEOUT_SEC", 0.1),
        ):
            rsps.add_callback(
                responses.POST,
                _TRANSCRIBE_URL_PATTERN,
                callback=_slow_response,
            )
            queue: asyncio.Queue[dict[str, str]] = asyncio.Queue()
            client = MaiTranscribeClient(queue)
            await client.start()
            client.feed_audio(_SILENCE_PCM)
            await client.stop()
            # バックグラウンドスレッドが実際のリクエスト送信を完了するまで待つ
            # (asyncio.wait_forのタイムアウトはスレッドの実行自体を中断しない)
            await asyncio.sleep(0.6)

        assert queue.empty()
