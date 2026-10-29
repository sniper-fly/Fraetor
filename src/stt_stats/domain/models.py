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


class SttLatencyStats(BaseModel):
    """サンプル群の応答時間の統計。時間は成功したリクエストだけから求める。"""

    model_config = ConfigDict(frozen=True)

    count: int
    failure_count: int
    failure_rate: float
    mean_sec: float | None
    median_sec: float | None
    p95_sec: float | None
    max_sec: float | None
    rtf: float | None
    """音声1秒あたりの処理時間。成功サンプルの応答時間の合計 ÷ 音声長の合計。
    平均の比ではなく合計の比にして、短い音声1件に引きずられにくくする。"""


class SttLatencyBand(BaseModel):
    """音声長の帯ごとの統計。同じ長さの音声同士で比べるために分ける。"""

    model_config = ConfigDict(frozen=True)

    label: str
    stats: SttLatencyStats | None
    """この帯のサンプルが無ければ None。"""


class SttLatencySummary(BaseModel):
    """エンジン別の応答時間の集計。"""

    model_config = ConfigDict(frozen=True)

    engine: str
    overall: SttLatencyStats
    bands: list[SttLatencyBand]
    recent_sec: list[float]
    """直近の成功サンプルの応答時間 (古い順)。推移の描画用。"""
