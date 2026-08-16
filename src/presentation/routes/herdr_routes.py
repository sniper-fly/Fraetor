from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.presentation.schemas.request_models import SendToHerdrRequest

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.recording_session_service import (
        RecordingSessionService,
    )
    from src.shared.herdr.ports import HerdrClientPort

router = APIRouter()


@router.post("/api/toggle-recording-and-send-to-herdr")
async def toggle_recording_and_send_to_herdr(request: Request) -> dict[str, object]:
    app_state: AppState = request.app.state.app_state
    recording_session_service: RecordingSessionService = (
        request.app.state.recording_session_service
    )
    herdr_client: HerdrClientPort = request.app.state.herdr_client

    if app_state.recording:
        await recording_session_service.stop_session(herdr_send_confirmed=True)
        return {"recording": False}

    target_pane_id = await herdr_client.get_focused_pane_id()
    await recording_session_service.start_session(
        target_pane_id=target_pane_id, herdr_requested=True
    )
    return {"recording": True, "target_pane_id": target_pane_id}


@router.get("/api/herdr-sessions")
async def list_herdr_sessions(request: Request) -> list[dict[str, str]]:
    herdr_client: HerdrClientPort = request.app.state.herdr_client
    sessions = await herdr_client.list_sessions()
    return [s.model_dump() for s in sessions]


@router.post("/api/send-to-herdr")
async def send_to_herdr(request: Request) -> dict[str, bool]:
    herdr_client: HerdrClientPort = request.app.state.herdr_client
    body = SendToHerdrRequest.model_validate(await request.json())
    success = await herdr_client.send_text(body.pane_id, body.text)
    return {"success": success}
