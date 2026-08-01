from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request

if TYPE_CHECKING:
    from src.transcript_history.domain.ports import HistoryRepositoryPort

router = APIRouter()


@router.get("/api/history")
async def history(request: Request) -> list[dict[str, object]]:
    history_repository: HistoryRepositoryPort = request.app.state.history_repository
    return history_repository.list_all()


@router.delete("/api/history/{session_id}")
async def delete_history(request: Request, session_id: str) -> dict[str, bool]:
    history_repository: HistoryRepositoryPort = request.app.state.history_repository
    deleted = history_repository.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}
