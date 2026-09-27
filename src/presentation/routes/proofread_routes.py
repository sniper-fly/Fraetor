from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request

from src.presentation.schemas.request_models import (
    FinalizeSessionRequest,
    ProofreadRequest,
)

if TYPE_CHECKING:
    from src.proofreading.application.proofread_text_use_case import (
        ProofreadTextUseCase,
    )
    from src.transcript_history.application.finalize_session_use_case import (
        FinalizeSessionUseCase,
    )
    from src.transcript_history.application.pending_session_store import (
        PendingSessionStore,
    )

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/proofread")
async def proofread_text(request: Request) -> dict[str, object]:
    body = ProofreadRequest.model_validate(await request.json())
    use_case: ProofreadTextUseCase = request.app.state.proofread_text_use_case
    text, proofread = await use_case.execute(body.text)
    return {"text": text, "proofread": proofread}


@router.post("/api/finalize-session")
async def finalize_session(request: Request) -> dict[str, bool]:
    pending_session_store: PendingSessionStore = request.app.state.pending_session_store
    body = FinalizeSessionRequest.model_validate(await request.json())
    pending = pending_session_store.pop(body.session_id)
    if pending is None:
        return {"ok": False}
    use_case: FinalizeSessionUseCase = request.app.state.finalize_session_use_case
    await use_case.execute(pending, text=body.text)
    return {"ok": True}
