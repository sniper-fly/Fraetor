"""録音済み音声ファイルを「マイク入力」として使う実サーバー経由のE2Eテスト。

`fraetor_server_with_audio` fixture は `FileAudioCapture` を注入した実サーバー
プロセスを起動する (`tests/e2e/e2e_entrypoint.py` 参照)。ハードウェアマイクや
仮想オーディオデバイスには依存せず、VAD の発話検知・無音タイムアウト・
STT 連携・SSE 配信という統合動作を実際の音声データで検証する。
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from collections.abc import Callable

_SESSION_END_WAIT_SEC = 30.0

# fixtures/audio/README.md に記載の想定発話。認識結果の突き合わせ表示にのみ使う
# (音声認識の表記揺れがあるため完全一致は求めない)
_EXPECTED_TEXTS = {
    "01_normal_speech.wav": "今日の会議の議事録をまとめました。よろしくお願いします。",
    "02_multiple_utterances.wav": "明日の予定を確認します。会議は午後からです。",
    "04_short_utterance.wav": "はい / テスト",
}


def _print_recognized(wav_filename: str, events: list[dict[str, str]]) -> None:
    texts = [
        json.loads(e["data"])["text"] for e in events if e["event"] == "recognized"
    ]
    print(
        f"\n[期待発話] {_EXPECTED_TEXTS[wav_filename]}\n[認識結果] {' / '.join(texts)}"
    )


async def _run_session(base_url: str) -> list[dict[str, str]]:
    """録音開始→session_endまでのSSEイベントを集めて返す。"""
    events: list[dict[str, str]] = []
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=None) as client,
        client.stream("GET", "/events") as sse_response,
    ):
        await client.post("/api/toggle-recording")

        async def collect() -> None:
            async for event in iter_sse_events(sse_response):
                events.append(event)
                if event["event"] == "session_end":
                    return

        await asyncio.wait_for(collect(), timeout=_SESSION_END_WAIT_SEC)
    return events


class TestFileAudioAndVad:
    async def test_normal_speech_triggers_recognition_and_auto_stop(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """01: 発話検知 → 無音タイムアウト短縮値で自動停止 → STT結果が非空"""
        base_url = fraetor_server_with_audio("01_normal_speech.wav")

        events = await _run_session(base_url)

        event_names = [e["event"] for e in events]
        assert "session_end" in event_names
        recognized = [e for e in events if e["event"] == "recognized"]
        assert recognized, "recognized イベントが1件も届かなかった"
        _print_recognized("01_normal_speech.wav", events)

    async def test_multiple_utterances_with_short_pause_stay_in_one_session(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """02: 短いポーズでは無音タイムアウトが発動せず、セッションが継続する"""
        base_url = fraetor_server_with_audio("02_multiple_utterances.wav")

        events = await _run_session(base_url)

        status_events = [
            json.loads(e["data"])["recording"] for e in events if e["event"] == "status"
        ]
        # status(true) の後に status(false) が1回だけ続くこと。
        # 途中で誤って追加の停止/開始が挟まっていれば3件以上になる
        # (短いポーズでタイムアウトしていない証跡)。
        assert status_events == [True, False]
        _print_recognized("02_multiple_utterances.wav", events)

    async def test_short_utterance_is_recognized(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """04: 短い発話でもVAD/STTが機能する"""
        base_url = fraetor_server_with_audio("04_short_utterance.wav")

        events = await _run_session(base_url)

        recognized = [e for e in events if e["event"] == "recognized"]
        assert recognized, "短い発話が認識されなかった"
        _print_recognized("04_short_utterance.wav", events)

    async def test_silence_only_stops_via_timeout_without_false_detection(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """03: 無音のみの音声ではVADが誤って発話と判定しない(誤検知なし)"""
        base_url = fraetor_server_with_audio("03_silence_only.wav")

        events = await _run_session(base_url)

        recognized = [e for e in events if e["event"] == "recognized"]
        assert not recognized, "無音のみの音声でrecognizedイベントが発生した(誤検知)"


class TestAudioDeviceFailure:
    async def test_missing_audio_device_broadcasts_error(
        self, fraetor_server_with_broken_audio: str
    ) -> None:
        """マイクデバイスが開けない状態で録音開始 → error イベントがSSE配信される"""
        async with (
            httpx.AsyncClient(base_url=fraetor_server_with_broken_audio) as client,
            client.stream("GET", "/events") as sse_response,
        ):
            await client.post("/api/toggle-recording")

            async def wait_for_error() -> dict[str, str]:
                async for event in iter_sse_events(sse_response):
                    if event["event"] == "error":
                        return event
                msg = "error イベントが届かなかった"
                raise AssertionError(msg)

            error_event = await asyncio.wait_for(wait_for_error(), timeout=10)
        assert "失敗" in error_event["data"]
