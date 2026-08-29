from __future__ import annotations

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.domain.ports import SttCapabilities

# 監視タスクがテスト中に勝手に発火しないよう、既定は十分長い閾値にする。
_NEVER_FIRES_SEC = 3600.0


def _setup_mocks(
    *, post_processing: bool = False
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """STTエンジン/VAD/AudioCaptureのモックとファクトリを返す。"""
    mock_stt = MagicMock()
    mock_stt.start = AsyncMock()
    mock_stt.stop = AsyncMock()
    mock_stt.flush = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing,
        post_processing=post_processing,
    )
    mock_vad = MagicMock()
    mock_vad.last_speech_time = time.monotonic()
    mock_vad.last_speech_start_sample = None
    mock_audio = MagicMock()
    mock_audio.start_recording = AsyncMock()
    mock_audio.stop_recording = AsyncMock()
    return mock_stt, mock_vad, mock_audio


def _make_coordinator(
    mock_audio: MagicMock,
    mock_stt: MagicMock,
    mock_vad: MagicMock,
    *,
    segment_silence_sec: float = _NEVER_FIRES_SEC,
) -> AudioPipelineCoordinator:
    return AudioPipelineCoordinator(
        mock_audio,
        lambda _q: mock_stt,
        lambda: mock_vad,
        lambda: segment_silence_sec,
    )


class TestStart:
    async def test_starts_stt_then_audio(self) -> None:
        """STT 接続 → マイクキャプチャ開始"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        await coordinator.start()

        mock_stt.start.assert_called_once()
        mock_audio.start_recording.assert_awaited_once_with(coordinator._on_audio_chunk)

    async def test_creates_dedicated_event_queue(self) -> None:
        """開始のたびにセッション専用のasyncio.Queueが生成される"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        await coordinator.start()

        assert coordinator.event_queue is not None

    async def test_audio_chunk_forwarded_to_stt_and_vad(self) -> None:
        """録音コールバックのPCMチャンクがSTTとVAD両方に転送される"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        coordinator._on_audio_chunk(b"pcm-bytes")

        mock_stt.feed_audio.assert_called_once_with(b"pcm-bytes")
        mock_vad.feed.assert_called_once_with(b"pcm-bytes")

    async def test_stt_start_failure_propagates_and_leaves_no_client(self) -> None:
        """STT開始失敗時は例外を伝播し、stt_clientを残さない"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_stt.start = AsyncMock(side_effect=RuntimeError("Auth failed"))
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        with contextlib.suppress(RuntimeError):
            await coordinator.start()

        assert coordinator.stt_client is None
        assert coordinator.event_queue is None

    async def test_audio_open_failure_stops_stt_and_propagates(self) -> None:
        """ストリームを開けない場合はSTTを停止し例外を伝播する"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_audio.start_recording = AsyncMock(
            side_effect=RuntimeError("No audio device")
        )
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        with contextlib.suppress(RuntimeError):
            await coordinator.start()

        mock_stt.stop.assert_called_once()
        assert coordinator.stt_client is None
        assert coordinator.event_queue is None


class TestStop:
    async def test_stops_recording_only_and_returns_ownership(self) -> None:
        """録音停止のみ行い、STT自体は停止せず所有権を呼び出し元に返す"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        result = await coordinator.stop()

        mock_audio.stop_recording.assert_awaited_once()
        mock_stt.stop.assert_not_called()
        assert coordinator.stt_client is None
        assert coordinator.event_queue is None
        assert result is not None
        stt_client, _event_queue = result
        assert stt_client is mock_stt

    async def test_returns_none_when_not_started(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        result = await coordinator.stop()

        assert result is None


class TestSegmentFlush:
    async def test_silence_triggers_flush_with_speech_start_sample(self) -> None:
        """無音区切りで、未送信の発話開始位置つきで flush が呼ばれる。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_vad.last_speech_start_sample = 4096
        coordinator = _make_coordinator(
            mock_audio, mock_stt, mock_vad, segment_silence_sec=0.05
        )

        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")  # VADの発話開始検出を模す
        await asyncio.sleep(0.1)
        await coordinator.stop()

        mock_stt.flush.assert_awaited_with(trim_before_sample=4096)

    async def test_monitor_does_not_start_before_start(self) -> None:
        """start() 前は監視を仕掛けない (録音していないのに flush しない)。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        _make_coordinator(mock_audio, mock_stt, mock_vad, segment_silence_sec=0.05)

        await asyncio.sleep(0.1)

        mock_stt.flush.assert_not_awaited()

    async def test_stop_halts_monitor_without_task_leak(self) -> None:
        """stop() 後は閾値を過ぎても flush されない (監視タスクが残らない)。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(
            mock_audio, mock_stt, mock_vad, segment_silence_sec=0.05
        )
        await coordinator.start()
        await coordinator.stop()
        mock_stt.flush.reset_mock()

        await asyncio.sleep(0.15)

        mock_stt.flush.assert_not_awaited()

    async def test_reads_segment_silence_sec_at_session_start(self) -> None:
        """閾値はセッション開始時に読む (設定変更が次セッションから反映される)。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_vad.last_speech_start_sample = 1000
        current = 3600.0
        coordinator = AudioPipelineCoordinator(
            mock_audio, lambda _q: mock_stt, lambda: mock_vad, lambda: current
        )
        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")  # 送るべき発話がある状態を作る
        await asyncio.sleep(0.1)
        assert mock_stt.flush.await_count == 0, "1回目は長い閾値なので発火しない"
        await coordinator.stop()

        current = 0.05
        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")
        await asyncio.sleep(0.1)
        await coordinator.stop()

        assert mock_stt.flush.await_count >= 1

    async def test_no_flush_after_stt_client_released(self) -> None:
        """stop() 後に監視が残っていても、STTを解放済みなら flush しない。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()
        await coordinator.stop()

        await coordinator._flush_segment()

        mock_stt.flush.assert_not_awaited()

    async def test_no_flush_during_silence_only_period(self) -> None:
        """新しい発話が一度もない間は flush 自体を呼ばない (無音のみを送らない)。

        `_on_audio_chunk` は VAD の検知結果に関わらずあらゆる音声チャンクを
        `feed_audio` に流すため、STT クライアント側の「新しいバイトがあるか」
        という no-op ガードは無音のみの区間では機能しない (無音のPCMそのものは
        増え続けるため)。「送るべき新しい発話があるか」を判定できるのは
        コーディネーターだけなので、ここで無音のみのflush呼び出し自体を
        抑止する必要がある (実機で無音中に一定間隔でAPI呼び出しが発生し
        続けていた不具合の回帰確認)。
        """
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        # 発話を検知しないまま音声チャンクだけが流れ続ける状態を模す。
        coordinator._on_audio_chunk(b"silence-chunk")
        coordinator._on_audio_chunk(b"silence-chunk")

        await coordinator._flush_segment()

        mock_stt.flush.assert_not_awaited()

    async def test_concurrent_flushes_are_serialized(self) -> None:
        """flush の並走を防ぐ (レスポンス順の入れ替わりでセグメント順序が崩れる)。

        2回とも送るべき発話がある状態を作る。1回目が発話Aの分を消費して
        `_pending_speech_start_sample` をリセットした後に発話Bを検出させ、
        2回目が正しくBの分を対象にする (でなければ2回目はno-opで即returnし、
        直列化の検証にならない)。
        """
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        events: list[str] = []

        async def slow_flush(*, trim_before_sample: int | None) -> None:
            events.append("enter")
            await asyncio.sleep(0.05)
            events.append("exit")

        mock_stt.flush = AsyncMock(side_effect=slow_flush)
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        mock_vad.last_speech_start_sample = 1000
        coordinator._on_audio_chunk(b"chunk-a")
        first = asyncio.create_task(coordinator._flush_segment())
        await asyncio.sleep(0)  # first がロック内で発話Aの分を消費するまで進める

        mock_vad.last_speech_start_sample = 5000
        coordinator._on_audio_chunk(b"chunk-b")
        second = asyncio.create_task(coordinator._flush_segment())

        await asyncio.gather(first, second)

        assert events == ["enter", "exit", "enter", "exit"]

    async def test_stop_waits_for_in_flight_flush(self) -> None:
        """進行中の flush を中断せず待つ (途中で切るとその区間が失われる)。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        completed = False

        async def slow_flush(*, trim_before_sample: int | None) -> None:
            nonlocal completed
            await asyncio.sleep(0.05)
            completed = True

        mock_stt.flush = AsyncMock(side_effect=slow_flush)
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()
        mock_vad.last_speech_start_sample = 1000
        coordinator._on_audio_chunk(b"chunk")
        flushing = asyncio.create_task(coordinator._flush_segment())
        await asyncio.sleep(0)

        await coordinator.stop()

        assert completed, "flush の完了を待たずに stop() が返った"
        await flushing

    async def test_flush_uses_earliest_unsent_speech_start_not_latest(self) -> None:
        """1回のflush対象区間に複数の発話が含まれる場合、最初の(まだ送信
        していない)発話の開始位置を使う。VADが最後に検出した発話開始位置で
        上書きされ、それより前の発話が消えてしまう挙動 (修正前のバグ) を
        防げていることを検証する。

        実運用では「短いポーズを挟んで複数文を話し、個々のポーズは
        segment_silence_sec未満なので発火せず、まとまった無音が来て初めて
        flushが発火する」ときに起こっていた。長い文章で最後の数言しか
        文字起こしされない、という報告に対応する。
        """
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        # 発話A(位置1000)を音声コールバック経由で検出 → 続けて、まだ
        # flushされないうちに発話B(位置5000)を検出した状態を模す
        # (どちらも未送信)。
        mock_vad.last_speech_start_sample = 1000
        coordinator._on_audio_chunk(b"chunk-a")
        mock_vad.last_speech_start_sample = 5000
        coordinator._on_audio_chunk(b"chunk-b")

        await coordinator._flush_segment()

        mock_stt.flush.assert_awaited_once_with(trim_before_sample=1000)

    async def test_delayed_flush_does_not_pick_up_speech_started_during_lock_wait(
        self,
    ) -> None:
        """flush が _flush_lock 待ち (直前のflushのHTTP応答待ちを想定) の間に
        次の発話が始まっても、待ち中に発話開始位置が上書きされない
        (修正前は上書きされてしまっていた)。

        実運用ではMAI TranscribeのAPI応答時間 (実測1〜2.5秒程度) の間に
        次の発話が始まると起こっていた。無音区切りの直後に次の発話を
        始めると前半が消える、という報告に対応する。
        """
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        mock_vad.last_speech_start_sample = 1000  # 発話Aの開始位置
        coordinator._on_audio_chunk(b"chunk-a")

        # 直前のflushがまだHTTP応答待ちでロックを保持している状況を模す。
        await coordinator._flush_lock.acquire()
        flush_task = asyncio.create_task(coordinator._flush_segment())
        await asyncio.sleep(0)  # flush_task がロック待ちに入るまで進める

        # 待機中に発話Bが始まった。
        mock_vad.last_speech_start_sample = 5000
        coordinator._on_audio_chunk(b"chunk-b")

        coordinator._flush_lock.release()
        await flush_task

        mock_stt.flush.assert_awaited_once_with(trim_before_sample=1000)


class TestSegmentLifecycleHook:
    async def test_start_calls_reset(self) -> None:
        """start() は毎セッションでフックの reset() を呼ぶ。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_hook = MagicMock()
        coordinator = AudioPipelineCoordinator(
            mock_audio,
            lambda _q: mock_stt,
            lambda: mock_vad,
            lambda: _NEVER_FIRES_SEC,
            segment_lifecycle_hook=mock_hook,
        )

        await coordinator.start()

        mock_hook.reset.assert_called_once()

    async def test_speech_start_triggers_hook_only_once(self) -> None:
        """未flush区間で最初の発話検知のみ on_speech_start が呼ばれる。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_vad.last_speech_start_sample = 1000
        mock_hook = MagicMock()
        coordinator = AudioPipelineCoordinator(
            mock_audio,
            lambda _q: mock_stt,
            lambda: mock_vad,
            lambda: _NEVER_FIRES_SEC,
            segment_lifecycle_hook=mock_hook,
        )
        await coordinator.start()

        coordinator._on_audio_chunk(b"chunk-a")
        coordinator._on_audio_chunk(b"chunk-a-again")

        mock_hook.on_speech_start.assert_called_once()

    async def test_flush_with_text_calls_on_flush_with_true(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_stt.flush = AsyncMock(return_value="認識結果")
        mock_vad.last_speech_start_sample = 1000
        mock_hook = MagicMock()
        coordinator = AudioPipelineCoordinator(
            mock_audio,
            lambda _q: mock_stt,
            lambda: mock_vad,
            lambda: _NEVER_FIRES_SEC,
            segment_lifecycle_hook=mock_hook,
        )
        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")

        await coordinator._flush_segment()

        mock_hook.on_flush.assert_called_once_with(produced_text=True)

    async def test_flush_with_empty_text_calls_on_flush_with_false(self) -> None:
        """認識結果が空 (recognizedイベント未発行) の場合は produced_text=False。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_stt.flush = AsyncMock(return_value="")
        mock_vad.last_speech_start_sample = 1000
        mock_hook = MagicMock()
        coordinator = AudioPipelineCoordinator(
            mock_audio,
            lambda _q: mock_stt,
            lambda: mock_vad,
            lambda: _NEVER_FIRES_SEC,
            segment_lifecycle_hook=mock_hook,
        )
        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")

        await coordinator._flush_segment()

        mock_hook.on_flush.assert_called_once_with(produced_text=False)

    async def test_none_hook_leaves_existing_flow_unaffected(self) -> None:
        """フック未注入 (None) でも既存の flush 挙動は変わらない。"""
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_stt.flush = AsyncMock(return_value="認識結果")
        mock_vad.last_speech_start_sample = 1000
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()
        coordinator._on_audio_chunk(b"chunk")

        await coordinator._flush_segment()

        mock_stt.flush.assert_awaited_once_with(trim_before_sample=1000)


class TestLastSpeechTime:
    async def test_returns_session_start_time_before_start(self) -> None:
        _, mock_vad, mock_audio = _setup_mocks()
        mock_stt, _, _ = _setup_mocks()
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)

        assert coordinator.last_speech_time() > 0

    async def test_returns_vad_last_speech_time_after_start(self) -> None:
        mock_stt, mock_vad, mock_audio = _setup_mocks()
        mock_vad.last_speech_time = 12345.0
        coordinator = _make_coordinator(mock_audio, mock_stt, mock_vad)
        await coordinator.start()

        assert coordinator.last_speech_time() == 12345.0
