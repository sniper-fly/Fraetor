from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_DEFAULT_PROOFREAD_PROMPT = (
    "音声認識で得られたテキストを校正してください。以下のルールに従ってください:\n"
    "- 誤字脱字、変換ミスを修正する\n"
    "- 不要な句読点や余分な記号を除去する\n"
    "- フィラーワード(えー、あの、えっと等)を除去する\n"
    "- 元のテキストの意味や表現をできる限り変えない\n"
    "- 校正結果のテキストのみを返す(説明や補足は一切付けない)"
)


class Settings(BaseModel):
    """アプリケーション定数群。シークレットは含まない (secrets_loader.Secrets 参照)。"""

    model_config = ConfigDict(frozen=True)

    # --- セッション ---
    max_session_duration_sec: int
    silence_timeout_sec: int

    # --- VAD (Silero) ---
    vad_threshold: float

    # --- STT 共通 ---
    stt_sample_rate: int

    # --- MAI Transcribe (バッチ, US リソース) ---
    mai_locale: str
    mai_model_name: str
    mai_timeout_sec: int

    # --- サーバー ---
    server_host: str
    server_port: int
    shutdown_delay_sec: float

    # --- SSE ---
    sse_keepalive_sec: int

    # --- 校正 (Proofreading) ---
    vertex_location: str
    gemini_model: str
    proofread_timeout_sec: int
    proofread_prompt: str

    # --- 履歴 ---
    history_dir: Path


def load_settings() -> Settings:
    """環境変数オーバーライドを適用して Settings を構築する。

    環境変数は E2E テストでタイムアウト・ポート・履歴ファイルを
    現実的な値/隔離された値に短縮/変更するためのもの。
    """
    history_dir = Path(
        os.environ.get("FRAETOR_HISTORY_DIR", "~/.voice-input")
    ).expanduser()
    return Settings(
        max_session_duration_sec=int(
            os.environ.get("FRAETOR_MAX_SESSION_DURATION_SEC", "600")
        ),
        silence_timeout_sec=int(os.environ.get("FRAETOR_SILENCE_TIMEOUT_SEC", "120")),
        vad_threshold=0.5,
        stt_sample_rate=16000,
        mai_locale="ja",
        mai_model_name="mai-transcribe-1",
        mai_timeout_sec=60,
        server_host="127.0.0.1",
        server_port=int(os.environ.get("FRAETOR_SERVER_PORT", "8765")),
        shutdown_delay_sec=0.5,
        sse_keepalive_sec=int(os.environ.get("FRAETOR_SSE_KEEPALIVE_SEC", "15")),
        vertex_location="global",
        gemini_model="gemini-3.1-flash-lite-preview",
        proofread_timeout_sec=15,
        proofread_prompt=_DEFAULT_PROOFREAD_PROMPT,
        history_dir=history_dir,
    )
