from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

from src.config import HISTORY_FILE, SSE_KEEPALIVE_SEC

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from src.state import AppState

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


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


@router.post("/api/correction-toggle")
async def correction_toggle(request: Request) -> dict[str, bool]:
    app_state = _get_state(request)
    app_state.correction_enabled = not app_state.correction_enabled
    logger.info("Correction toggled: %s", app_state.correction_enabled)
    return {"correction_enabled": app_state.correction_enabled}


@router.get("/api/correction-status")
async def correction_status(request: Request) -> dict[str, bool]:
    app_state = _get_state(request)
    return {"correction_enabled": app_state.correction_enabled}


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
