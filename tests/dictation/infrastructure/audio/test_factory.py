from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from src.dictation.infrastructure.audio.factory import create_audio_capture
from src.dictation.infrastructure.audio.per_session_capture import (
    PerSessionStreamCapture,
)
from src.dictation.infrastructure.audio.persistent_capture import (
    PersistentStreamCapture,
)

if TYPE_CHECKING:
    import pytest

_SAMPLE_RATE = 16000


class TestCreateAudioCapture:
    def test_darwin_uses_persistent_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """macOS では CoreAudio デッドロック回避のため常駐ストリーム方式"""
        monkeypatch.setattr(sys, "platform", "darwin")
        assert isinstance(create_audio_capture(_SAMPLE_RATE), PersistentStreamCapture)

    def test_linux_uses_per_session_stream(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Linux では従来どおり録音中のみマイクを掴むセッション開閉方式"""
        monkeypatch.setattr(sys, "platform", "linux")
        assert isinstance(create_audio_capture(_SAMPLE_RATE), PerSessionStreamCapture)
