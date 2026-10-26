"""Azure MAI Transcribe との実クラウド通信を、本番と同じ配線で検証するE2Eテスト。

実クラウド通信を許容する (低頻度実行のため)。エンジンは `Container` が
実際の資格情報・動的設定で組み立てた `stt_engine_factory` から生成する。
そのため「Fraetorの設定がライブラリへ正しく配線され、実APIで認識できるか」の確認になる。

MAI APIの異常応答 (401/429/5xx/タイムアウト) の挙動は、ライブラリ側
(fraetor-dictation) の責務なのでライブラリのテストで検証している。
"""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from src.containers import Container

if TYPE_CHECKING:
    from dictation import SttEvent

_AUDIO_DIR = Path(__file__).parent / "fixtures" / "audio"

# fixtures/audio/README.md に記載の想定発話。認識結果の突き合わせ表示にのみ使う
# (音声認識の表記揺れがあるため完全一致は求めない)
_EXPECTED_TEXT = "今日の会議の議事録をまとめました。よろしくお願いします。"


class TestRealCloudCommunication:
    async def test_normal_speech_is_transcribed_via_real_api(self) -> None:
        """正常系: 実クラウド通信で音声を送信し、認識結果が空でなく返る"""
        wav_path = _AUDIO_DIR / "01_normal_speech.wav"
        with wave.open(str(wav_path), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())

        queue: asyncio.Queue[SttEvent] = asyncio.Queue()
        engine = Container().stt_engine_factory()(queue)
        await engine.start()
        engine.feed_audio(pcm)
        await engine.stop()

        assert not queue.empty(), "実クラウド通信でrecognizedイベントが届かなかった"
        event = queue.get_nowait()
        assert event.type == "recognized"
        assert event.text, "認識結果テキストが空だった"
        print(f"\n[期待発話] {_EXPECTED_TEXT}\n[認識結果] {event.text}")
