from __future__ import annotations

import base64

from openai import AsyncAzureOpenAI

from src.intent_translation.domain.ports import IntentTranslatorPort

_MAX_COMPLETION_TOKENS = 2500
"""実測: 300では出力が空になった。reasoningトークン消費分の余裕を持たせる。"""


class AzureOpenAIIntentTranslator(IntentTranslatorPort):
    """Azure OpenAI互換チャット補完APIを使った意図翻訳クライアント。

    `max_tokens`は非対応(実機で400エラー`unsupported_parameter`)のため
    `max_completion_tokens`を使う。API例外はキャッチせず伝播させる
    (フォールバックはUseCase層の責務、`VertexGeminiProofreader`と同方針)。
    """

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        deployment: str,
        api_version: str,
        prompt: str,
    ) -> None:
        self._client = AsyncAzureOpenAI(
            azure_endpoint=endpoint, api_key=api_key, api_version=api_version
        )
        self._deployment = deployment
        self._prompt = prompt

    async def translate(self, text: str, screenshot_png: bytes) -> str:
        if not text.strip():
            return text
        image_data_url = (
            f"data:image/png;base64,{base64.b64encode(screenshot_png).decode('ascii')}"
        )
        response = await self._client.chat.completions.create(
            model=self._deployment,
            max_completion_tokens=_MAX_COMPLETION_TOKENS,
            messages=[
                {"role": "system", "content": self._prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        )
        content = response.choices[0].message.content
        return content.strip() if content else text
