from __future__ import annotations

from typing import TYPE_CHECKING

from src.stt_stats.application.latency_hook_adapter import SttLatencyRecorder
from src.stt_stats.domain.ports import SttLatencyRepositoryPort

if TYPE_CHECKING:
    from src.stt_stats.domain.models import SttLatencySample


class _Repo(SttLatencyRepositoryPort):
    def __init__(self) -> None:
        self.saved: list[SttLatencySample] = []

    def save(self, sample: SttLatencySample) -> None:
        self.saved.append(sample)

    def list_since(self, since: object) -> list[SttLatencySample]:
        return []


def test_notification_is_saved_as_sample() -> None:
    repo = _Repo()

    SttLatencyRecorder(repo).on_stt_completed(
        engine="gemini",
        phase="flush",
        duration_sec=1.5,
        audio_duration_sec=4.0,
        succeeded=False,
    )

    [sample] = repo.saved
    assert (sample.engine, sample.phase, sample.duration_sec) == (
        "gemini",
        "flush",
        1.5,
    )
    assert sample.audio_duration_sec == 4.0
    assert sample.succeeded is False
    assert sample.recorded_at.tzinfo is not None
