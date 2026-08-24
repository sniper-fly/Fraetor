from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

from src.dictation.application.app_state import AppState
from src.dictation.application.audio_pipeline_coordinator import (
    AudioPipelineCoordinator,
)
from src.dictation.application.recording_session_service import (
    RecordingSessionService,
)
from src.dictation.application.segment_accumulator import SegmentAccumulator
from src.dictation.application.stt_event_relay import SttEventRelay
from src.dictation.application.transcription_queue import TranscriptionQueue
from src.dictation.domain.ports import SttCapabilities, SttEnginePort
from src.dictation.infrastructure.messaging.sse_broadcaster import SSEBroadcaster
from src.shared.config.dynamic_settings import DynamicSettings
from tests.fakes import InMemorySettingsRepository

_MAX_DURATION_SEC = 600
_SILENCE_TIMEOUT_SEC = 120


def _make_service(
    *,
    max_duration_sec: float = _MAX_DURATION_SEC,
    silence_timeout_sec: float = _SILENCE_TIMEOUT_SEC,
    post_processing: bool = False,
    stt_start_side_effect: Exception | None = None,
    audio_start_side_effect: Exception | None = None,
) -> tuple[
    RecordingSessionService,
    AppState,
    MagicMock,
    TranscriptionQueue,
    InMemorySettingsRepository,
]:
    app_state = AppState(broadcaster=SSEBroadcaster())

    mock_stt = MagicMock(spec=SttEnginePort)
    mock_stt.start = AsyncMock(side_effect=stt_start_side_effect)
    mock_stt.stop = AsyncMock()
    mock_stt.feed_audio = MagicMock()
    mock_stt.capabilities = SttCapabilities(
        streaming=not post_processing, post_processing=post_processing
    )
    mock_vad = MagicMock()
    mock_vad.last_speech_time = time.monotonic()
    mock_vad.last_speech_start_sample = None
    mock_audio = MagicMock()
    mock_audio.start_recording = AsyncMock(side_effect=audio_start_side_effect)
    mock_audio.stop_recording = AsyncMock()

    # 無音区切りの逐次 flush はここでの検証対象ではないため、テスト中に
    # 発火しない閾値を渡して切り離す (検証は
    # tests/dictation/application/test_audio_pipeline_coordinator.py)。
    audio_pipeline = AudioPipelineCoordinator(
        mock_audio, lambda _q: mock_stt, lambda: mock_vad, lambda: 3600.0
    )
    accumulator = SegmentAccumulator(app_state.broadcaster)
    event_relay = SttEventRelay(app_state, accumulator)
    transcription_queue = TranscriptionQueue(app_state, accumulator)
    transcription_queue.start()
    settings_repository = InMemorySettingsRepository(
        DynamicSettings(
            max_session_duration_sec=max_duration_sec,
            silence_timeout_sec=silence_timeout_sec,
            segment_silence_sec=min(3.0, silence_timeout_sec / 2),
        )
    )
    service = RecordingSessionService(
        app_state,
        audio_pipeline,
        event_relay,
        transcription_queue,
        settings_repository=settings_repository,
    )
    return service, app_state, mock_stt, transcription_queue, settings_repository


class TestStartSession:
    async def test_creates_session_with_correct_fields(self) -> None:
        """セッション開始 → RecordingSession 作成"""
        service, app_state, _, queue, _repo = _make_service()

        await service.start_session()

        assert app_state.recording is True
        session = app_state.current_session
        assert session is not None
        assert session.segments == []

        await service.stop_session()
        await queue.shutdown(timeout=1)

    async def test_broadcasts_recording_started(self) -> None:
        service, app_state, _, queue, _repo = _make_service()
        sub = app_state.broadcaster.subscribe()

        await service.start_session()

        msg = sub.get_nowait()
        assert msg["event"] == "status"
        assert json.loads(msg["data"])["recording"] is True

        await service.stop_session()
        await queue.shutdown(timeout=1)

    async def test_ignores_start_when_already_recording(self) -> None:
        service, _, mock_stt, queue, _repo = _make_service()
        await service.start_session()
        mock_stt.start.reset_mock()

        await service.start_session()

        mock_stt.start.assert_not_called()

        await service.stop_session()
        await queue.shutdown(timeout=1)

    async def test_records_target_pane_id_when_herdr_requested(self) -> None:
        service, app_state, _, queue, _repo = _make_service()

        await service.start_session(target_pane_id="w1:p1", herdr_requested=True)

        session = app_state.current_session
        assert session is not None
        assert session.target_pane_id == "w1:p1"

        await service.stop_session()
        await queue.shutdown(timeout=1)

    async def test_broadcasts_target_pane_id_and_herdr_requested(self) -> None:
        service, app_state, _, queue, _repo = _make_service()
        sub = app_state.broadcaster.subscribe()

        await service.start_session(
            target_pane_id="w1:p1",
            target_pane_label="Claude Code",
            herdr_requested=True,
        )

        msg = sub.get_nowait()
        data = json.loads(msg["data"])
        assert data["target_pane_id"] == "w1:p1"
        assert data["target_pane_label"] == "Claude Code"
        assert data["herdr_requested"] is True

        await service.stop_session()
        await queue.shutdown(timeout=1)

    async def test_broadcasts_no_target_pane_id_for_plain_start(self) -> None:
        """既存の引数なし呼び出しの回帰確認。

        target_pane_id/herdr_requestedは既定値のままになる。
        """
        service, app_state, _, queue, _repo = _make_service()
        sub = app_state.broadcaster.subscribe()

        await service.start_session()

        msg = sub.get_nowait()
        data = json.loads(msg["data"])
        assert data["target_pane_id"] is None
        assert data["target_pane_label"] is None
        assert data["herdr_requested"] is False

        await service.stop_session()
        await queue.shutdown(timeout=1)


class TestStopSession:
    async def test_stops_recording_immediately_without_waiting_for_stt(self) -> None:
        """stop_sessionはSTT完了を待たず即座に返る"""
        service, app_state, mock_stt, queue, _repo = _make_service(post_processing=True)
        await service.start_session()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        await asyncio.wait_for(service.stop_session(), timeout=0.1)

        assert app_state.recording is False
        assert app_state.current_session is None

        stt_stop_proceed.set()
        await queue.shutdown(timeout=1)

    async def test_stop_when_not_recording_is_noop(self) -> None:
        service, app_state, _, queue, _repo = _make_service()

        await service.stop_session()

        assert app_state.recording is False
        await queue.shutdown(timeout=1)

    async def test_broadcasts_status_recording_false(self) -> None:
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()
        sub = app_state.broadcaster.subscribe()

        await service.stop_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        status_msgs = [m for m in messages if m["event"] == "status"]
        assert len(status_msgs) == 1
        data = json.loads(status_msgs[0]["data"])
        assert data["recording"] is False
        assert data["herdr_send_confirmed"] is False

        await queue.shutdown(timeout=1)

    async def test_broadcasts_session_id_and_herdr_send_confirmed_on_stop(self) -> None:
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()
        session_id = app_state.current_session.id  # type: ignore[union-attr]
        sub = app_state.broadcaster.subscribe()

        await service.stop_session(herdr_send_confirmed=True)

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        status_msgs = [m for m in messages if m["event"] == "status"]
        data = json.loads(status_msgs[0]["data"])
        assert data["session_id"] == session_id
        assert data["herdr_send_confirmed"] is True

        await queue.shutdown(timeout=1)

    async def test_timed_out_flag_reaches_finalized_session(self) -> None:
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()

        await service.stop_session(timed_out=True)
        await queue.shutdown(timeout=1)

        assert app_state.pending_sessions[-1].timed_out is True

    async def test_enqueues_transcription_job_on_stop(self) -> None:
        """停止時に文字起こしジョブがキューに投入され、非同期に処理される"""
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()

        await service.stop_session()
        await queue.shutdown(timeout=1)

        assert len(app_state.pending_sessions) == 1
        assert app_state.current_session is None

    async def test_recognized_events_reach_pending_session_after_queue_processing(
        self,
    ) -> None:
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()

        event_queue = service._audio_pipeline.event_queue
        assert event_queue is not None
        event_queue.put_nowait({"type": "recognized", "text": "テスト"})
        await asyncio.sleep(0.05)

        await service.stop_session()
        await queue.shutdown(timeout=1)

        assert app_state.pending_sessions[-1].full_text == "テスト"

    async def test_stop_waits_for_in_flight_flush_before_enqueueing(self) -> None:
        """無音区切りのflushが進行中にstop_sessionが呼ばれても、flushの
        完了を待ってからTranscriptionQueueへジョブを投入する。

        待たずに投入すると、TranscriptionQueue側のdrain()がevent_queueへの
        recognized到着より先に走ってしまい、flush中の発話テキストが
        欠落する (`AudioPipelineCoordinator.stop()`の`_flush_lock`待ちが、
        `RecordingSessionService`経由の統合フローでも効いているかの検証)。
        """
        service, app_state, mock_stt, queue, _repo = _make_service()
        await service.start_session()

        event_queue = service._audio_pipeline.event_queue
        assert event_queue is not None

        async def slow_flush(*, trim_before_sample: int | None) -> None:
            await asyncio.sleep(0.05)
            event_queue.put_nowait({"type": "recognized", "text": "発話1"})

        mock_stt.flush = AsyncMock(side_effect=slow_flush)

        service._audio_pipeline._vad.last_speech_start_sample = 1000
        service._audio_pipeline._on_audio_chunk(b"chunk")
        flush_task = asyncio.create_task(service._audio_pipeline._flush_segment())
        await asyncio.sleep(0)  # flushがロックを取得しHTTP応答待ちに入るまで進める

        await service.stop_session()
        await queue.shutdown(timeout=1)

        assert app_state.pending_sessions[-1].full_text == "発話1", (
            "flush完了を待たずにenqueueすると、drain()がこのテキストを取りこぼす"
        )
        await flush_task


class TestSttEventProcessing:
    async def test_full_text_assembled_from_segments(self) -> None:
        """全セグメントのテキスト結合"""
        service, app_state, _, queue, _repo = _make_service()
        await service.start_session()

        event_queue = service._audio_pipeline.event_queue
        assert event_queue is not None
        event_queue.put_nowait({"type": "recognized", "text": "こんにちは。"})
        event_queue.put_nowait({"type": "recognized", "text": "お元気ですか。"})
        await asyncio.sleep(0.05)

        await service.stop_session()
        await queue.shutdown(timeout=1)

        assert app_state.pending_sessions[-1].full_text == "こんにちは。お元気ですか。"


class TestIncrementalSegments:
    """無音区切りの flush が既存の追記経路をそのまま通ることを確認する。

    プラン §5 の「`SegmentAccumulator`/SSE/フロントエンドは変更不要」という
    前提が、実際に flush 由来のイベントでも成立していることを担保する。
    """

    async def test_flushed_segments_are_appended_in_order_during_recording(
        self,
    ) -> None:
        """録音中の flush 結果が、到着順にセグメントとして追記・配信される。"""
        service, app_state, _stt, queue, _repo = _make_service()
        recognized: list[dict[str, object]] = []
        subscriber = app_state.broadcaster.subscribe()
        await service.start_session()

        event_queue = service._audio_pipeline.event_queue
        assert event_queue is not None
        # flush が recognized を投入する状況を再現する (STT 側の送信は
        # tests/.../test_mai_transcribe_client.py で検証済み)
        for text in ("1つ目。", "2つ目。", "3つ目。"):
            event_queue.put_nowait({"type": "recognized", "text": text})
            await asyncio.sleep(0.01)

        session = app_state.current_session
        assert session is not None
        assert [s.id for s in session.segments] == [0, 1, 2], "録音中に逐次追記される"
        assert [s.text for s in session.segments] == ["1つ目。", "2つ目。", "3つ目。"]

        while not subscriber.empty():
            event = subscriber.get_nowait()
            if event["event"] == "recognized":
                recognized.append(json.loads(event["data"]))

        assert [d["segment_id"] for d in recognized] == [0, 1, 2], (
            "セグメントIDが到着順に配信される"
        )

        await service.stop_session()
        await queue.shutdown(timeout=1)

        assert app_state.pending_sessions[-1].full_text == "1つ目。2つ目。3つ目。"

    async def test_concurrent_flushes_preserve_order_end_to_end(self) -> None:
        """発話1(処理が遅いflush)の最中に発話2の無音区切りが来ても、
        flush呼び出し順(=発話順)でセグメントが確定する。

        `test_audio_pipeline_coordinator.py::test_concurrent_flushes_are_serialized`
        はflush呼び出し引数(trim_before_sample)の直列化のみを検証している。
        ここでは`_flush_lock`の直列化がSegmentAccumulatorまで正しく伝播し、
        最終的なfull_text/セグメント順序が「後から終わった短い発話が先に
        確定する」形で崩れないことを確認する。
        """
        service, app_state, mock_stt, queue, _repo = _make_service()
        await service.start_session()

        event_queue = service._audio_pipeline.event_queue
        assert event_queue is not None
        coordinator = service._audio_pipeline
        call_count = 0

        async def flush(*, trim_before_sample: int | None) -> str:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # 発話1: 処理(HTTP応答)が遅い長い発話を想定
                await asyncio.sleep(0.05)
                event_queue.put_nowait({"type": "recognized", "text": "発話1"})
                return "発話1"
            # 発話2: 即座に応答が返る短い発話を想定
            event_queue.put_nowait({"type": "recognized", "text": "発話2"})
            return "発話2"

        mock_stt.flush = AsyncMock(side_effect=flush)

        coordinator._vad.last_speech_start_sample = 1000
        coordinator._on_audio_chunk(b"chunk-a")
        first_flush = asyncio.create_task(coordinator._flush_segment())
        await asyncio.sleep(0)  # 1回目がロックを取得しHTTP応答待ちに入るまで進める

        coordinator._vad.last_speech_start_sample = 5000
        coordinator._on_audio_chunk(b"chunk-b")
        second_flush = asyncio.create_task(coordinator._flush_segment())

        await asyncio.gather(first_flush, second_flush)
        await asyncio.sleep(0.01)

        session = app_state.current_session
        assert session is not None
        assert [s.text for s in session.segments] == ["発話1", "発話2"], (
            "直列化が効いていなければ発話2が先に確定してしまう"
        )

        await service.stop_session()
        await queue.shutdown(timeout=1)
        assert app_state.pending_sessions[-1].full_text == "発話1発話2"


class TestSessionTimeout:
    """`DynamicSettings` のタイムアウトは float なので、テストでは実時間
    消費を抑えるため 0.05 秒のような小さい値を使う。
    """

    async def test_auto_stops_after_max_duration(self) -> None:
        """最大セッション時間経過 → 超過時は自動で録音停止"""
        service, app_state, mock_stt, queue, _repo = _make_service(
            max_duration_sec=0.05, silence_timeout_sec=10
        )

        await service.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.15)

        assert app_state.recording is False
        assert app_state.current_session is None
        mock_stt.stop.assert_called_once()

        await queue.shutdown(timeout=1)

    async def test_auto_stops_after_silence_timeout(self) -> None:
        """発話なしのまま silence_timeout_sec 経過 → 自動で録音停止"""
        service, app_state, _, queue, _repo = _make_service(
            max_duration_sec=10, silence_timeout_sec=0.05
        )

        await service.start_session()
        assert app_state.recording is True

        await asyncio.sleep(0.15)

        assert app_state.recording is False
        assert app_state.current_session is None

        await queue.shutdown(timeout=1)

    async def test_next_session_uses_updated_timeout(self) -> None:
        """`update()` した値は次の `start_session()` から反映される。

        1回目のセッションは長いタイムアウトで開始し、その間に設定を
        0.05秒へ縮める。1回目は停止せず、停止後に開始した2回目だけが
        新しい値でタイムアウトすることを確認する。
        """
        service, app_state, _, queue, repo = _make_service(
            max_duration_sec=600, silence_timeout_sec=120
        )
        await service.start_session()

        repo.update(
            DynamicSettings(
                max_session_duration_sec=0.05,
                silence_timeout_sec=120,
                segment_silence_sec=3.0,
            )
        )
        await asyncio.sleep(0.15)
        assert app_state.recording is True, "実行中セッションには反映しない"

        await service.stop_session()
        await service.start_session()
        await asyncio.sleep(0.15)

        assert app_state.recording is False

        await queue.shutdown(timeout=1)


class TestSessionStartFailure:
    async def test_stt_failure_aborts_session(self) -> None:
        """STT開始失敗時はセッションを中止する"""
        service, app_state, _, queue, _repo = _make_service(
            stt_start_side_effect=RuntimeError("Auth failed")
        )

        await service.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

        await queue.shutdown(timeout=1)

    async def test_stt_failure_broadcasts_error(self) -> None:
        service, app_state, _, queue, _repo = _make_service(
            stt_start_side_effect=RuntimeError("Auth failed")
        )
        sub = app_state.broadcaster.subscribe()

        await service.start_session()

        messages = []
        while not sub.empty():
            messages.append(sub.get_nowait())
        error_msgs = [m for m in messages if m["event"] == "error"]
        assert len(error_msgs) == 1
        assert "失敗" in json.loads(error_msgs[0]["data"])["message"]

        await queue.shutdown(timeout=1)

    async def test_stream_open_failure_aborts_session(self) -> None:
        """ストリームを開けない場合はセッションを中止する"""
        service, app_state, _, queue, _repo = _make_service(
            audio_start_side_effect=RuntimeError("No audio device")
        )

        await service.start_session()

        assert app_state.recording is False
        assert app_state.current_session is None

        await queue.shutdown(timeout=1)


class TestConcurrentStartStop:
    """stop_session中にstart_sessionが呼ばれた場合の振る舞いテスト。

    文字起こし処理はTranscriptionQueueに委譲されるため、stop_sessionは
    STT完了を待たずに即座に返る。これによりstop直後のstartがブロック
    されないことを検証する (キュー化の主目的)。
    """

    async def test_start_does_not_wait_for_transcription_to_complete(self) -> None:
        """stop_session中のSTT API呼び出しが長時間かかっても、
        start_sessionは待たされず即座に次のセッションを開始できる。"""
        service, app_state, mock_stt, queue, _repo = _make_service(post_processing=True)
        await service.start_session()

        assert app_state.current_session is not None
        first_session_id = app_state.current_session.id

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        await service.stop_session()
        await stt_stop_entered.wait()

        await asyncio.wait_for(service.start_session(), timeout=0.1)

        assert app_state.recording is True
        assert app_state.current_session is not None
        assert app_state.current_session.id != first_session_id

        second_session_id = app_state.current_session.id

        stt_stop_proceed.set()
        await service.stop_session()
        await queue.shutdown(timeout=1)

        pending_ids = [s.id for s in app_state.pending_sessions]
        assert pending_ids == [first_session_id, second_session_id], (
            "後発(second)が先にキュー投入されても、両セッションが取り違え・"
            "欠落せず投入順(=録音開始順)で残る"
        )

    async def test_three_sessions_queued_while_first_still_processing(self) -> None:
        """1件目がキューで処理中の間に2件目・3件目まで開始/停止しても、
        3セッションとも取り違え・欠落せず投入順で区別されて残る。"""
        service, app_state, mock_stt, queue, _repo = _make_service(post_processing=True)

        stt_stop_entered = asyncio.Event()
        stt_stop_proceed = asyncio.Event()

        async def slow_stt_stop() -> None:
            stt_stop_entered.set()
            await stt_stop_proceed.wait()

        mock_stt.stop = slow_stt_stop

        await service.start_session()
        first_session_id = app_state.current_session.id  # type: ignore[union-attr]
        await service.stop_session()
        await stt_stop_entered.wait()

        # 1件目はまだTranscriptionQueueでstop()待ちのまま、2件目・3件目を
        # 連続して開始/終了する (いずれも即座に返り、キューに積まれるだけ)。
        mock_stt.stop = AsyncMock()
        await service.start_session()
        second_session_id = app_state.current_session.id  # type: ignore[union-attr]
        await service.stop_session()

        await service.start_session()
        third_session_id = app_state.current_session.id  # type: ignore[union-attr]
        await service.stop_session()

        stt_stop_proceed.set()
        await queue.shutdown(timeout=1)

        pending_ids = [s.id for s in app_state.pending_sessions]
        assert pending_ids == [first_session_id, second_session_id, third_session_id]

    async def test_double_stop_second_call_is_noop(self) -> None:
        """録音していない状態でのstop_sessionは何もしない (冪等)。"""
        service, _, mock_stt, queue, _repo = _make_service(post_processing=True)
        await service.start_session()

        mock_stt.stop = AsyncMock()

        await service.stop_session()
        await service.stop_session()

        await queue.shutdown(timeout=1)
