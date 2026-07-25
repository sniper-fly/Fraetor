from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from src.vad import SpeechActivityDetector

_WINDOW_SAMPLES = 512


def _silence_bytes(num_windows: int = 1) -> bytes:
    return np.zeros(_WINDOW_SAMPLES * num_windows, dtype=np.int16).tobytes()


@patch("src.vad.VADIterator")
@patch("src.vad.load_silero_vad")
class TestSpeechActivityDetector:
    def test_initial_last_speech_time_is_set(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """モデルロード直後から last_speech_time が monotonic 時刻を持つ。"""
        mock_iter_cls.return_value.triggered = False
        det = SpeechActivityDetector()

        assert det.last_speech_time > 0

    def test_silence_does_not_update_last_speech_time(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """VADが無音(triggered=False, resultなし)と判定した間は更新しない。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SpeechActivityDetector()
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
        det = SpeechActivityDetector()
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
        det = SpeechActivityDetector()
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time > t0

    def test_buffers_partial_chunks_until_window_size(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """512サンプル未満の断片は蓄積し、512サンプルに達するまで推論しない。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.return_value = None
        det = SpeechActivityDetector()
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
        det = SpeechActivityDetector()

        det.feed(_silence_bytes(num_windows=3))

        assert mock_iter.call_count == 3

    def test_inference_error_is_swallowed_and_does_not_raise(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """VAD推論が例外を投げても feed() 自体は例外を伝播させない(録音を止めない)。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.side_effect = RuntimeError("inference boom")
        det = SpeechActivityDetector()

        det.feed(_silence_bytes())  # 例外にならない

    def test_recovers_after_inference_error(
        self, mock_load: MagicMock, mock_iter_cls: MagicMock
    ) -> None:
        """推論エラー後も次のfeed呼び出しで正常に動作を継続できる。"""
        mock_iter = mock_iter_cls.return_value
        mock_iter.triggered = False
        mock_iter.side_effect = [RuntimeError("boom"), None]
        det = SpeechActivityDetector()

        det.feed(_silence_bytes())
        mock_iter.side_effect = None
        mock_iter.triggered = True
        mock_iter.return_value = None
        t0 = det.last_speech_time

        det.feed(_silence_bytes())

        assert det.last_speech_time > t0
