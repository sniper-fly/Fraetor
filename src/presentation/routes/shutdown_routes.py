from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

if TYPE_CHECKING:
    from src.dictation.application.app_state import AppState
    from src.dictation.application.recording_session_service import (
        RecordingSessionService,
    )
    from src.dictation.application.transcription_queue import TranscriptionQueue
    from src.shared.process.ports import ProcessShutdownerPort

router = APIRouter()


@router.post("/api/shutdown")
async def shutdown(request: Request) -> dict[str, bool]:
    app_state: AppState = request.app.state.app_state
    recording_session_service: RecordingSessionService = (
        request.app.state.recording_session_service
    )
    transcription_queue: TranscriptionQueue = request.app.state.transcription_queue
    mai_timeout_sec: float = request.app.state.mai_timeout_sec
    if app_state.recording:
        await recording_session_service.stop_session()
    # キュー内の残ジョブ (session_end配信・履歴保存を含む) の完了を待ってから
    # shutdown を通知する。先に通知するとブラウザがSSE接続を諦め、
    # 文字起こし結果が失われる。
    await transcription_queue.shutdown(timeout=mai_timeout_sec + 5)
    await app_state.broadcaster.broadcast("shutdown", {})
    shutdowner: ProcessShutdownerPort = request.app.state.shutdowner
    shutdown_delay_sec: float = request.app.state.shutdown_delay_sec
    shutdowner.schedule(shutdown_delay_sec)
    return {"ok": True}
