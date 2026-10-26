from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Query, Request

# FastAPI はハンドラのアノテーションをランタイムに解決するため、
# TYPE_CHECKING ブロックには移せない。
from src.stt_stats.domain.models import SttLatencySummary  # noqa: TC001

if TYPE_CHECKING:
    from src.stt_stats.application.summarize_latency_use_case import (
        SummarizeLatencyUseCase,
    )

router = APIRouter()


@router.get("/api/stats/stt")
async def stt_stats(
    request: Request,
    period: Annotated[Literal["today", "7d"], Query()] = "today",
) -> dict[str, object]:
    """エンジン別のSTT応答時間の集計と、現在選択中のエンジンを返す。"""
    use_case: SummarizeLatencyUseCase = request.app.state.summarize_latency_use_case
    summaries: list[SttLatencySummary] = use_case.execute(period)
    current_engine = request.app.state.settings_repository.get().stt.engine
    return {
        "period": period,
        "current_engine": current_engine,
        "engines": [s.model_dump() for s in summaries],
    }
