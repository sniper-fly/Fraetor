from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types
from google.oauth2 import service_account

from src.models import ProofreadResult


class Proofreader:
    """Vertex AI Gemini を使ったテキスト校正クライアント。"""

    def __init__(
        self,
        sa_info: dict[str, Any],
        project: str,
        location: str,
        model: str,
        prompt: str,
    ) -> None:
        credentials = service_account.Credentials.from_service_account_info(  # type: ignore[no-untyped-call]
            sa_info,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        self._client = genai.Client(
            vertexai=True,
            project=project,
            location=location,
            credentials=credentials,
        )
        self._model = model
        self._prompt = prompt

    async def proofread(self, text: str) -> str:
        """テキストを校正し、校正済みテキストを返す。

        空テキストの場合はそのまま返す。
        """
        if not text.strip():
            return text

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=self._prompt,
                response_mime_type="application/json",
                response_schema=ProofreadResult,
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, ProofreadResult):
            return parsed.corrected_text
        return text
