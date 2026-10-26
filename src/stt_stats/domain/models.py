from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import BaseModel, ConfigDict


class SttLatencySample(BaseModel):
    """STT 1リクエスト分の応答時間の記録。"""

    model_config = ConfigDict(frozen=True)

    recorded_at: datetime
    engine: str
    phase: str
    duration_sec: float
    audio_duration_sec: float
    succeeded: bool


class SttLatencySummary(BaseModel):
    """エンジン別の応答時間の集計。時間は成功したリクエストだけから求める。"""

    model_config = ConfigDict(frozen=True)

    engine: str
    count: int
    failure_count: int
    failure_rate: float
    mean_sec: float | None
    median_sec: float | None
    p95_sec: float | None
    max_sec: float | None
    recent_sec: list[float]
    """直近の成功サンプルの応答時間 (古い順)。推移の描画用。"""
