from __future__ import annotations

from pydantic import BaseModel


class ProofreadRequest(BaseModel):
    text: str


class FinalizeSessionRequest(BaseModel):
    text: str
