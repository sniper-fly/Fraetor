from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from src.stt_stats.domain.models import SttLatencySample
from src.stt_stats.infrastructure.jsonl_latency_repository import (
    JsonlLatencyRepository,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def _sample(at: datetime, duration: float = 1.0) -> SttLatencySample:
    return SttLatencySample(
        recorded_at=at,
        engine="mai",
        phase="stop",
        duration_sec=duration,
        audio_duration_sec=2.0,
        succeeded=True,
    )


def test_roundtrip_creates_directory_and_filters_by_since(tmp_path: Path) -> None:
    repo = JsonlLatencyRepository(tmp_path / "new_dir")
    old = _sample(_NOW - timedelta(days=2), 9.0)
    recent = _sample(_NOW, 1.0)

    repo.save(old)
    repo.save(recent)

    assert repo.list_since(_NOW - timedelta(days=1)) == [recent]
    assert repo.list_since(_NOW - timedelta(days=3)) == [old, recent]


def test_missing_file_gives_empty_list(tmp_path: Path) -> None:
    assert JsonlLatencyRepository(tmp_path).list_since(_NOW) == []


def test_broken_line_is_skipped(tmp_path: Path) -> None:
    repo = JsonlLatencyRepository(tmp_path)
    repo.save(_sample(_NOW))
    with (tmp_path / "stt_latency.jsonl").open("a", encoding="utf-8") as f:
        f.write("{broken\n")
    repo.save(_sample(_NOW, 2.0))

    assert [s.duration_sec for s in repo.list_since(_NOW)] == [1.0, 2.0]
