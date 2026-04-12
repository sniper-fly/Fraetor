from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.clipboard import copy_to_clipboard
from src.config import HISTORY_FILE, PROOFREAD_TIMEOUT_SEC, SSE_KEEPALIVE_SEC
from src.history import delete_session, save_session

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from src.proofreader import Proofreader
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


class ProofreadRequest(BaseModel):
    text: str


@router.post("/api/proofread")
async def proofread_text(request: Request) -> dict[str, object]:
    body = ProofreadRequest.model_validate(await request.json())
    proofreader: Proofreader | None = request.app.state.proofreader
    if proofreader is None:
        return {"text": body.text, "proofread": False}
    try:
        result = await asyncio.wait_for(
            proofreader.proofread(body.text),
            timeout=PROOFREAD_TIMEOUT_SEC,
        )
        return {"text": result, "proofread": True}
    except Exception:
        logger.exception("Proofreading failed")
        return {"text": body.text, "proofread": False}


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


@router.delete("/api/history/{session_id}")
async def delete_history(session_id: str) -> dict[str, bool]:
    deleted = delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


@router.post("/api/shutdown")
async def shutdown(request: Request) -> dict[str, bool]:
    app_state = _get_state(request)
    session_manager = _get_session_manager(request)
    if app_state.recording:
        await session_manager.stop_session()
    await app_state.broadcaster.broadcast("shutdown", {})
    loop = asyncio.get_running_loop()
    loop.call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)
    return {"ok": True}
