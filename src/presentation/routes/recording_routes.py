from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from src.dictation.application.app_state import AppState
    from src.dictation.application.recording_session_service import (
        RecordingSessionService,
    )
    from src.shared.config.ports import SettingsRepositoryPort

router = APIRouter()


@router.get("/events")
async def events(request: Request) -> EventSourceResponse:
    app_state: AppState = request.app.state.app_state
    settings_repository: SettingsRepositoryPort = request.app.state.settings_repository
    # キープアライブ間隔は接続時に1回読む。長時間つながり続ける SSE の
    # 途中で間隔を変えても既存接続には反映しない (再接続で反映される)。
    sse_keepalive_sec: float = settings_repository.get().sse_keepalive_sec

    async def event_generator() -> AsyncGenerator[dict[str, str]]:
        queue = app_state.broadcaster.subscribe()
        try:
            while True:
                try:
                    message = await asyncio.wait_for(
                        queue.get(), timeout=sse_keepalive_sec
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
    app_state: AppState = request.app.state.app_state
    recording_session_service: RecordingSessionService = (
        request.app.state.recording_session_service
    )
    if app_state.recording:
        await recording_session_service.stop_session()
    else:
        await recording_session_service.start_session()
    return {"recording": app_state.recording}
