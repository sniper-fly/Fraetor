from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.stt_stats.application.summarize_latency_use_case import (
    SummarizeLatencyUseCase,
)
from src.stt_stats.domain.models import SttLatencySample
from src.stt_stats.domain.ports import SttLatencyRepositoryPort

_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class _FakeRepository(SttLatencyRepositoryPort):
    def __init__(self, samples: list[SttLatencySample]) -> None:
        self._samples = samples
        self.since: datetime | None = None

    def save(self, sample: SttLatencySample) -> None:
        self._samples.append(sample)

    def list_since(self, since: datetime) -> list[SttLatencySample]:
        self.since = since
        return [s for s in self._samples if s.recorded_at >= since]


def _sample(
    duration: float, *, engine: str = "mai", ok: bool = True, at: datetime = _NOW
) -> SttLatencySample:
    return SttLatencySample(
        recorded_at=at,
        engine=engine,
        phase="flush",
        duration_sec=duration,
        audio_duration_sec=3.0,
        succeeded=ok,
    )


def _use_case(samples: list[SttLatencySample]) -> SummarizeLatencyUseCase:
    return SummarizeLatencyUseCase(_FakeRepository(samples), now_fn=lambda: _NOW)


class TestStatistics:
    def test_mean_median_p95_max_and_count(self) -> None:
        durations = [float(i) for i in range(1, 21)]  # 1..20

        [summary] = _use_case([_sample(d) for d in durations]).execute("today")

        assert summary.count == 20
        assert summary.mean_sec == pytest.approx(10.5)
        assert summary.median_sec == pytest.approx(10.5)
        assert summary.p95_sec == 19.0  # 最近傍順位: ceil(0.95*20)=19番目
        assert summary.max_sec == 20.0

    def test_failures_count_in_rate_but_not_in_latency(self) -> None:
        samples = [_sample(1.0), _sample(3.0), _sample(60.0, ok=False)]

        [summary] = _use_case(samples).execute("today")

        assert summary.count == 3
        assert summary.failure_count == 1
        assert summary.failure_rate == pytest.approx(1 / 3)
        assert summary.mean_sec == 2.0
        assert summary.max_sec == 3.0

    def test_only_failures_gives_no_latency_values(self) -> None:
        [summary] = _use_case([_sample(60.0, ok=False)]).execute("today")

        assert summary.failure_rate == 1.0
        assert summary.mean_sec is None
        assert summary.p95_sec is None
        assert summary.recent_sec == []

    def test_engines_are_summarized_separately(self) -> None:
        samples = [_sample(1.0, engine="mai"), _sample(5.0, engine="gemini")]

        summaries = _use_case(samples).execute("today")

        assert {s.engine: s.mean_sec for s in summaries} == {"gemini": 5.0, "mai": 1.0}

    def test_recent_keeps_latest_successes_in_order(self) -> None:
        samples = [_sample(float(i)) for i in range(40)]

        [summary] = _use_case(samples).execute("today")

        assert summary.recent_sec == [float(i) for i in range(10, 40)]


class TestPeriod:
    def test_seven_days_includes_boundary_and_excludes_older(self) -> None:
        inside = _sample(1.0, at=_NOW - timedelta(days=7))
        outside = _sample(9.0, at=_NOW - timedelta(days=7, seconds=1))

        [summary] = _use_case([inside, outside]).execute("7d")

        assert summary.count == 1

    def test_today_starts_at_local_midnight(self) -> None:
        repo = _FakeRepository([])

        SummarizeLatencyUseCase(repo, now_fn=lambda: _NOW).execute("today")

        local_midnight = _NOW.astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert repo.since == local_midnight

    def test_no_samples_gives_empty_list(self) -> None:
        assert _use_case([]).execute("today") == []
