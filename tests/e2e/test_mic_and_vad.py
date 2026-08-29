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
    "06_long_speech.wav": (
        "今日の定例会議について報告します。"
        "まず進捗ですが、予定していたタスクはほぼ完了しています。"
        "次に課題ですが、外部APIとの連携部分で仕様の確認が必要です。"
        "最後に来週のスケジュールですが、月曜に詳細を詰める予定です。"
        "以上、よろしくお願いします。"
    ),
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

    async def test_multiple_utterances_are_flushed_as_separate_segments(
        self, fraetor_server_with_audio: Callable[..., str]
    ) -> None:
        """02: 発話間のポーズで逐次flushされ、1セッション中に複数recognizedが届く

        `02_multiple_utterances.wav` (README記載の目安は0.5秒程度のポーズだが、
        実測では発話者によって1秒前後になり得る) に対し、`segment_silence_sec`
        をE2E既定の1.0秒より十分短く (0.3秒) 上書きすることで、ポーズの実測値
        のばらつきに関わらず確実にポーズ区間をまたいでflushが発火する状態を作る。
        上の `test_multiple_utterances_with_short_pause_stay_in_one_session` は
        セッションが割れないことを検証するのに対し、本テストはセッション内で
        セグメントが分かれて届くこと (逐次文字起こし本体) を検証する。
        """
        base_url = fraetor_server_with_audio(
            "02_multiple_utterances.wav",
            settings_overrides={"segment_silence_sec": 0.3},
        )

        events = await _run_session(base_url)

        recognized = [
            json.loads(e["data"]) for e in events if e["event"] == "recognized"
        ]
        assert len(recognized) >= 2, (
            "ポーズによる逐次flushで複数のrecognizedが届くはずが1件以下だった"
        )
        session_ids = {r["session_id"] for r in recognized}
        assert len(session_ids) == 1, "全recognizedは同一セッションに属するはず"
        assert [r["segment_id"] for r in recognized] == list(range(len(recognized))), (
            "segment_idは到着順に0から連番のはず"
        )
        _print_recognized("02_multiple_utterances.wav", events)

    async def test_no_utterance_is_lost_when_flush_overlaps_next_utterance(
        self, fraetor_server_with_audio: Callable[..., str]
    ) -> None:
        """02: flushのHTTP応答待ち中に次の発話が始まっても、両方の発話が残る

        `02_multiple_utterances.wav` の発話区間の切れ目は1箇所 (実測1.15秒)
        のみ。`segment_silence_sec` をそれより十分小さい0.5秒に設定して
        1つ目の発話が終わった直後にflushが発火するようにする (0.05秒等の
        極端な値はVADのウィンドウ単位(32ms)の揺らぎで発話中に誤発火し、
        単語単位に刻んでしまい別の失敗を招くため避ける)。MAI Transcribeの
        HTTP応答 (実測1〜2.5秒程度) が返る前に2つ目の発話 (1.15秒後) が
        始まるため、「flushが待機中に上書きされた発話開始位置を使って前の
        発話を消してしまう」という既知バグの再現条件を実クラウド経由で
        再現する。`test_multiple_utterances_are_flushed_as_separate_segments`
        は件数と順序だけを見ており、内容の欠落は検証していなかったため、
        両方の発話の内容が残っていることまで確認する。
        """
        base_url = fraetor_server_with_audio(
            "02_multiple_utterances.wav",
            settings_overrides={"segment_silence_sec": 0.5},
        )

        events = await _run_session(base_url)

        recognized = [
            json.loads(e["data"]) for e in events if e["event"] == "recognized"
        ]
        full_text = "".join(r["text"] for r in recognized)
        assert "明日" in full_text, f"1つ目の発話が失われた: {full_text}"
        assert "午後" in full_text, f"2つ目の発話が失われた: {full_text}"
        _print_recognized("02_multiple_utterances.wav", events)

    async def test_long_speech_all_sentences_survive_incremental_flush(
        self, fraetor_server_with_audio: Callable[..., str]
    ) -> None:
        """06: 長い文章を無音区切りで区切って逐次flushしても、全文が失われず届く

        文と文の間の短いポーズ (実測0.71〜0.87秒) はデフォルトの
        `segment_silence_sec` (3秒) では区切られないため、このテストでは
        0.45秒に短縮して複数回のflushを確実に発生させる。文中の息継ぎ
        (実測最大0.29秒) より十分大きく、文間のポーズ(実測最小0.71秒)より
        十分小さい値を選ぶことで、文の途中でflushが発火して極端に短い
        音声クリップが送られる(Azure側の認識精度が落ちてテキストが
        欠落しうる)ことを避ける。「1回のflush対象区間に複数の発話が
        含まれると、最後の発話より前が消える」という既知バグの回帰確認。
        `max_session_duration_sec`/`silence_timeout_sec` も音声の長さ
        (30秒、末尾に10秒以上の無音) に合わせて上書きする。
        """
        base_url = fraetor_server_with_audio(
            "06_long_speech.wav",
            settings_overrides={
                "segment_silence_sec": 0.45,
                "silence_timeout_sec": 5,
                "max_session_duration_sec": 30,
            },
        )

        events = await _run_session(base_url)

        recognized = [
            json.loads(e["data"]) for e in events if e["event"] == "recognized"
        ]
        assert len(recognized) >= 2, "複数回のflushが発生するはず"
        full_text = "".join(r["text"] for r in recognized)
        for keyword in ["定例会議", "進捗", "課題", "スケジュール", "よろしく"]:
            assert keyword in full_text, f"'{keyword}' を含む文が失われた: {full_text}"
        _print_recognized("06_long_speech.wav", events)

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
