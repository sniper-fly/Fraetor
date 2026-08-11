from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from src.dictation.infrastructure.vad.silero_vad_detector import (
    SileroSpeechActivityDetector,
)

_WINDOW_SAMPLES = 512
_SAMPLE_RATE = 16000
_THRESHOLD = 0.5


def _silence_bytes(num_windows: int = 1) -> bytes:
    return np.zeros(_WINDOW_SAMPLES * num_windows, dtype=np.int16).tobytes()


@patch("src.dictation.infrastructure.vad.silero_vad_detector.VADIterator")
@patch("src.dictation.infrastructure.vad.silero_vad_detector.load_silero_vad")
class TestSileroSpeechActivityDetector:
    def test_initial_last_speech_time_is_set(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """モデルロード直後から last_speech_time が monotonic 時刻を持つ。"""
        mock_iter_cls.return_value.triggered = False
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        assert det.last_speech_time > 0

    def test_silence_does_not_update_last_speech_time(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """VADが無音(triggered=False, resultなし)と判定した間は更新しない。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time == t0

    def test_triggered_state_updates_last_speech_time(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """発話中(triggered=True)は毎ウィンドウ last_speech_time が更新される。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = True
        mock_iter.return_value = None
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time > t0

    def test_speech_end_event_updates_last_speech_time(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """発話終了確定 (end イベント) の瞬間にも last_speech_time が更新される。

        end イベント発生時、VADIterator.triggered は既に False に戻っているため、
        triggered だけを見ていると発話終了の瞬間を取り落とす。
        """
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = {"end": 1000}
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time > t0

    def test_speech_start_sample_is_none_until_speech_detected(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """発話が一度も検出されていない間は last_speech_start_sample が None。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        det.feed(_silence_bytes())

        assert det.last_speech_start_sample is None

    def test_start_event_records_speech_start_sample(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """start イベントの sample 位置をそのまま保持する (前方無音の削除位置)。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = True
        mock_iter.return_value = {"start": 4096}
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        det.feed(_silence_bytes())

        assert det.last_speech_start_sample == 4096

    def test_start_sample_is_overwritten_by_later_speech(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """2度目の発話開始で位置が更新される (直近の発話開始だけを保持する)。

        flush は「直近の無音区間の直前の発話」を送るため、過去の start を
        持ち続けると既に送信済みの区間を再送してしまう。
        """
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = True
        mock_iter.return_value = {"start": 4096}
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        det.feed(_silence_bytes())

        mock_iter.return_value = {"start": 32768}
        det.feed(_silence_bytes())

        assert det.last_speech_start_sample == 32768

    def test_end_event_does_not_change_speech_start_sample(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """end イベントでは開始位置を書き換えない (発話区間の先頭を保つ)。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = True
        mock_iter.return_value = {"start": 4096}
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        det.feed(_silence_bytes())

        mock_iter.triggered = False
        mock_iter.return_value = {"end": 20000}
        det.feed(_silence_bytes())

        assert det.last_speech_start_sample == 4096

    def test_buffers_partial_chunks_until_window_size(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """512サンプル未満の断片は蓄積し、512サンプルに達するまで推論しない。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)
        partial = np.zeros(128, dtype=np.int16).tobytes()

        det.feed(partial)
        det.feed(partial)
        det.feed(partial)
        assert mock_iter.call_count == 0

        det.feed(partial)
        assert mock_iter.call_count == 1

    def test_feeds_multiple_windows_from_larger_chunk(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """512サンプルの倍数を一度に渡すと、その回数だけ推論される。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        det.feed(_silence_bytes(num_windows=3))

        assert mock_iter.call_count == 3

    def test_inference_error_is_swallowed_and_does_not_raise(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """VAD推論が例外を投げても feed() 自体は例外を伝播させない(録音を止めない)。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.side_effect = RuntimeError("inference boom")
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        det.feed(_silence_bytes())  # 例外にならない

    def test_recovers_after_inference_error(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """推論エラー後も次のfeed呼び出しで正常に動作を継続できる。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.side_effect = [RuntimeError("boom"), None]
        det = SileroSpeechActivityDetector(_SAMPLE_RATE, _THRESHOLD)

        det.feed(_silence_bytes())
        mock_iter.side_effect = None
        mock_iter.triggered = True
        mock_iter.return_value = None
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time > t0
