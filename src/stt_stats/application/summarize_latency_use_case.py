from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from src.stt_stats.domain.models import (
    SttLatencyBand,
    SttLatencySample,
    SttLatencyStats,
    SttLatencySummary,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.stt_stats.domain.ports import SttLatencyRepositoryPort

Period = Literal["today", "7d"]

_RECENT_LIMIT = 30


def _percentile(sorted_values: list[float], ratio: float) -> float:
    """最近傍順位法のパーセンタイル。"""
    rank = math.ceil(ratio * len(sorted_values))
    return sorted_values[max(rank, 1) - 1]


# 音声長の帯 (秒)。(ラベル, 下限を含む, 上限を含まない)。応答時間の大半は
# 音声長に比例しない固定の遅延なので、短い発話と長い発話を同じ平均に混ぜない。
_BANDS: tuple[tuple[str, float, float], ...] = (
    ("3秒未満", 0.0, 3.0),
    ("3〜10秒", 3.0, 10.0),
    ("10秒以上", 10.0, math.inf),
)


def _stats(samples: list[SttLatencySample]) -> SttLatencyStats:
    ok = [s for s in samples if s.succeeded]
    failures = len(samples) - len(ok)
    durations = sorted(s.duration_sec for s in ok)
    audio_total = sum(s.audio_duration_sec for s in ok)
    return SttLatencyStats(
        count=len(samples),
        failure_count=failures,
        failure_rate=failures / len(samples),
        mean_sec=statistics.fmean(durations) if ok else None,
        median_sec=statistics.median(durations) if ok else None,
        p95_sec=_percentile(durations, 0.95) if ok else None,
        max_sec=durations[-1] if ok else None,
        rtf=sum(durations) / audio_total if audio_total > 0 else None,
    )


def _summarize(engine: str, samples: list[SttLatencySample]) -> SttLatencySummary:
    bands = []
    for label, low, high in _BANDS:
        in_band = [s for s in samples if low <= s.audio_duration_sec < high]
        bands.append(
            SttLatencyBand(label=label, stats=_stats(in_band) if in_band else None)
        )
    ok = [s.duration_sec for s in samples if s.succeeded]
    return SttLatencySummary(
        engine=engine,
        overall=_stats(samples),
        bands=bands,
        recent_sec=ok[-_RECENT_LIMIT:],
    )


class SummarizeLatencyUseCase:
    """期間内のSTT応答時間をエンジン別に集計する。"""

    def __init__(
        self,
        repository: SttLatencyRepositoryPort,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._now_fn = now_fn

    def execute(self, period: Period) -> list[SttLatencySummary]:
        since = self._period_start(period)
        by_engine: dict[str, list[SttLatencySample]] = {}
        for sample in self._repository.list_since(since):
            by_engine.setdefault(sample.engine, []).append(sample)
        return [_summarize(engine, by_engine[engine]) for engine in sorted(by_engine)]

    def _period_start(self, period: Period) -> datetime:
        """「今日」は端末のローカル日付の0時から、「7日」は現在から7日前。"""
        now = self._now_fn()
        if period == "7d":
            return now - timedelta(days=7)
        return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
