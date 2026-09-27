from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class InterimEvent(BaseModel):
    """未確定の認識中テキスト(ストリーミングSTTのみ発火)。"""

    type: Literal["interim"] = "interim"
    text: str


class RecognizedEvent(BaseModel):
    """確定した認識結果テキスト(1回のflush/stopごとに1件)。"""

    type: Literal["recognized"] = "recognized"
    text: str


SttEvent = Annotated[InterimEvent | RecognizedEvent, Field(discriminator="type")]
