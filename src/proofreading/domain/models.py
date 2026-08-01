from __future__ import annotations

from pydantic import BaseModel


class ProofreadResult(BaseModel):
    """LLM校正の構造化出力スキーマ。"""

    corrected_text: str
