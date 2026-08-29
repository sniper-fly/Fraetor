from __future__ import annotations

from pydantic import BaseModel


class ProofreadRequest(BaseModel):
    text: str


class FinalizeSessionRequest(BaseModel):
    session_id: str
    text: str


class SendToHerdrRequest(BaseModel):
    pane_id: str
    text: str
