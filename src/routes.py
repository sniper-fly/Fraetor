from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.clipboard import copy_to_clipboard
from src.config import HISTORY_FILE, SSE_KEEPALIVE_SEC
from src.history import save_session

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from src.session_manager import SessionManager
    from src.state import AppState

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


def _get_session_manager(request: Request) -> SessionManager:
    session_manager: SessionManager = request.app.state.session_manager
    return session_manager


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    templates_dir = request.app.state.templates_dir
    html_path = templates_dir / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@router.get("/events")
async def events(request: Request) -> EventSourceResponse:
    app_state = _get_state(request)

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        queue = app_state.broadcaster.subscribe()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=SSE_KEEPALIVE_SEC
                    )
                    yield message
                except TimeoutError:
                    yield {"event": "keepalive", "data": ""}
        except asyncio.CancelledError:
            pass
        finally:
            app_state.broadcaster.unsubscribe(queue)

    return EventSourceResponse(event_generator())


@router.post("/api/toggle-recording")
async def toggle_recording(request: Request) -> dict[str, bool]:
    app_state = _get_state(request)
    session_manager = _get_session_manager(request)
    if app_state.recording:
        await session_manager.stop_session()
    else:
        await session_manager.start_session()
    return {"recording": app_state.recording}


@router.get("/api/history")
async def history() -> list[dict[str, object]]:
    if not HISTORY_FILE.exists():
        return []
    text = HISTORY_FILE.read_text(encoding="utf-8").strip()
    if not text:
        return []
    sessions: list[dict[str, object]] = [
        json.loads(line) for line in text.splitlines() if line.strip()
    ]
    sessions.reverse()
    return sessions


class FinalizeSessionRequest(BaseModel):
    text: str


@router.post("/api/finalize-session")
async def finalize_session(request: Request) -> dict[str, bool]:
    app_state = _get_state(request)
    body = FinalizeSessionRequest.model_validate(await request.json())
    pending = app_state.pending_session
    if pending is None:
        return {"ok": False}
    try:
        await copy_to_clipboard(body.text)
    except Exception:
        logger.exception("Failed to copy text to clipboard")
    try:
        save_session(pending, text_override=body.text)
    except Exception:
        logger.exception("Failed to save session history")
    app_state.pending_session = None
    return {"ok": True}
