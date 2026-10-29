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
    duration: float,
    *,
    engine: str = "mai",
    ok: bool = True,
    at: datetime = _NOW,
    audio: float = 3.0,
) -> SttLatencySample:
    return SttLatencySample(
        recorded_at=at,
        engine=engine,
        phase="flush",
        duration_sec=duration,
        audio_duration_sec=audio,
        succeeded=ok,
    )


def _use_case(samples: list[SttLatencySample]) -> SummarizeLatencyUseCase:
    return SummarizeLatencyUseCase(_FakeRepository(samples), now_fn=lambda: _NOW)


class TestStatistics:
    def test_mean_median_p95_max_and_count(self) -> None:
        durations = [float(i) for i in range(1, 21)]  # 1..20

        [summary] = _use_case([_sample(d) for d in durations]).execute("today")

        overall = summary.overall
        assert overall.count == 20
        assert overall.mean_sec == pytest.approx(10.5)
        assert overall.median_sec == pytest.approx(10.5)
        assert overall.p95_sec == 19.0  # 最近傍順位: ceil(0.95*20)=19番目
        assert overall.max_sec == 20.0

    def test_failures_count_in_rate_but_not_in_latency(self) -> None:
        samples = [_sample(1.0), _sample(3.0), _sample(60.0, ok=False)]

        [summary] = _use_case(samples).execute("today")

        overall = summary.overall
        assert overall.count == 3
        assert overall.failure_count == 1
        assert overall.failure_rate == pytest.approx(1 / 3)
        assert overall.mean_sec == 2.0
        assert overall.max_sec == 3.0

    def test_only_failures_gives_no_latency_values(self) -> None:
        [summary] = _use_case([_sample(60.0, ok=False)]).execute("today")

        assert summary.overall.failure_rate == 1.0
        assert summary.overall.mean_sec is None
        assert summary.overall.p95_sec is None
        assert summary.overall.rtf is None
        assert summary.recent_sec == []

    def test_engines_are_summarized_separately(self) -> None:
        samples = [_sample(1.0, engine="mai"), _sample(5.0, engine="gemini")]

        summaries = _use_case(samples).execute("today")

        assert {s.engine: s.overall.mean_sec for s in summaries} == {
            "gemini": 5.0,
            "mai": 1.0,
        }

    def test_recent_keeps_latest_successes_in_order(self) -> None:
        samples = [_sample(float(i)) for i in range(40)]

        [summary] = _use_case(samples).execute("today")

        assert summary.recent_sec == [float(i) for i in range(10, 40)]


class TestBandsAndRtf:
    def test_samples_are_split_by_audio_duration(self) -> None:
        samples = [
            _sample(1.0, audio=1.0),
            _sample(2.0, audio=2.9),
            _sample(3.0, audio=3.0),  # 下限は帯に含む
            _sample(4.0, audio=9.9),
            _sample(5.0, audio=10.0),  # 上限は帯に含まない
        ]

        [summary] = _use_case(samples).execute("today")

        counts = {b.label: b.stats.count if b.stats else 0 for b in summary.bands}
        assert counts == {"3秒未満": 2, "3〜10秒": 2, "10秒以上": 1}

    def test_empty_band_has_no_stats(self) -> None:
        [summary] = _use_case([_sample(1.0, audio=1.0)]).execute("today")

        assert [b.stats is None for b in summary.bands] == [False, True, True]

    def test_rtf_is_ratio_of_totals_not_mean_of_ratios(self) -> None:
        """短い音声1件の悪い比に引きずられないよう、合計の比で求める。"""
        samples = [_sample(1.0, audio=1.0), _sample(3.0, audio=30.0)]

        [summary] = _use_case(samples).execute("today")

        assert summary.overall.rtf == pytest.approx(4.0 / 31.0)

    def test_rtf_ignores_failed_samples(self) -> None:
        samples = [_sample(2.0, audio=10.0), _sample(60.0, audio=10.0, ok=False)]

        [summary] = _use_case(samples).execute("today")

        assert summary.overall.rtf == pytest.approx(2.0 / 10.0)


class TestPeriod:
    def test_seven_days_includes_boundary_and_excludes_older(self) -> None:
        inside = _sample(1.0, at=_NOW - timedelta(days=7))
        outside = _sample(9.0, at=_NOW - timedelta(days=7, seconds=1))

        [summary] = _use_case([inside, outside]).execute("7d")

        assert summary.overall.count == 1

    def test_today_starts_at_local_midnight(self) -> None:
        repo = _FakeRepository([])

        SummarizeLatencyUseCase(repo, now_fn=lambda: _NOW).execute("today")

        local_midnight = _NOW.astimezone().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        assert repo.since == local_midnight

    def test_no_samples_gives_empty_list(self) -> None:
        assert _use_case([]).execute("today") == []
