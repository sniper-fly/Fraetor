from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from src.stt_stats.domain.models import SttLatencySample
from src.stt_stats.domain.ports import SttLatencyRepositoryPort

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

logger = logging.getLogger(__name__)


class JsonlLatencyRepository(SttLatencyRepositoryPort):
    """JSONLファイルによるSTT応答時間の永続化 (履歴と同じディレクトリに置く)。"""

    def __init__(self, history_dir: Path) -> None:
        self._history_dir = history_dir
        self._file = history_dir / "stt_latency.jsonl"

    def save(self, sample: SttLatencySample) -> None:
        self._history_dir.mkdir(parents=True, exist_ok=True)
        with self._file.open("a", encoding="utf-8") as f:
            f.write(sample.model_dump_json() + "\n")

    def list_since(self, since: datetime) -> list[SttLatencySample]:
        if not self._file.exists():
            return []
        samples: list[SttLatencySample] = []
        for line in self._file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                sample = SttLatencySample.model_validate_json(line)
            except ValidationError:
                logger.warning("Skipping broken latency record: %s", line[:80])
                continue
            if sample.recorded_at >= since:
                samples.append(sample)
        return samples
