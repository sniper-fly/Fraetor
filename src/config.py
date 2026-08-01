import os
from pathlib import Path
from typing import Any

from src.secrets_loader import load_secrets

# --- セッション ---
# E2E テストでタイムアウト待ちを現実的な時間に短縮するための環境変数オーバーライド
MAX_SESSION_DURATION_SEC: int = int(
    os.environ.get("FRAETOR_MAX_SESSION_DURATION_SEC", "600")
)
SILENCE_TIMEOUT_SEC: int = int(os.environ.get("FRAETOR_SILENCE_TIMEOUT_SEC", "120"))

# --- VAD (Silero) ---
VAD_THRESHOLD: float = 0.5

# --- STT 共通 ---
STT_SAMPLE_RATE: int = 16000

# --- MAI Transcribe (バッチ, US リソース) ---
# SDK はリソースエンドポイント形式
# (https://<resource>.cognitiveservices.azure.com) を期待
MAI_ENDPOINT: str = ""
MAI_LOCALE: str = "ja"
MAI_MODEL_NAME: str = "mai-transcribe-1"
MAI_TIMEOUT_SEC: int = 60

# --- サーバー ---
SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = int(os.environ.get("FRAETOR_SERVER_PORT", "8765"))
SHUTDOWN_DELAY_SEC: float = 0.5

# --- SSE ---
# E2E テストで keepalive 動作の待ち時間を短縮するための環境変数オーバーライド
SSE_KEEPALIVE_SEC: int = int(os.environ.get("FRAETOR_SSE_KEEPALIVE_SEC", "15"))

# --- 校正 (Proofreading) ---
VERTEX_LOCATION: str = "global"
GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
PROOFREAD_TIMEOUT_SEC: int = 15
PROOFREAD_PROMPT: str = (
    "音声認識で得られたテキストを校正してください。以下のルールに従ってください:\n"
    "- 誤字脱字、変換ミスを修正する\n"
    "- 不要な句読点や余分な記号を除去する\n"
    "- フィラーワード(えー、あの、えっと等)を除去する\n"
    "- 元のテキストの意味や表現をできる限り変えない\n"
    "- 校正結果のテキストのみを返す(説明や補足は一切付けない)"
)

# --- シークレット (init_secrets() で設定) ---
MAI_API_KEY: str = ""
VERTEX_SA_INFO: dict[str, Any] = {}
VERTEX_PROJECT: str = ""


def init_secrets() -> None:
    """AWS SSM Parameter Store からシークレットを取得し、モジュール変数に設定する。"""
    global MAI_API_KEY, MAI_ENDPOINT, VERTEX_SA_INFO, VERTEX_PROJECT  # noqa: PLW0603
    s = load_secrets()
    MAI_API_KEY = s.mai_api_key
    MAI_ENDPOINT = s.mai_endpoint
    VERTEX_SA_INFO = s.vertex_sa_info
    VERTEX_PROJECT = s.vertex_project


def validate_api_keys() -> list[str]:
    """APIキーの設定状態を確認し、警告メッセージのリストを返す。"""
    warnings: list[str] = []
    if not MAI_API_KEY:
        warnings.append("MAI_API_KEY が未設定です。音声認識は利用できません。")
    if not VERTEX_SA_INFO:
        warnings.append("VERTEX_SA_INFO が未設定です。テキスト校正は利用できません。")
    return warnings


# --- 履歴 ---
# E2E テストで本番の履歴ファイルを汚染しないための環境変数オーバーライド
HISTORY_DIR: Path = Path(
    os.environ.get("FRAETOR_HISTORY_DIR", "~/.voice-input")
).expanduser()
HISTORY_FILE: Path = HISTORY_DIR / "history.jsonl"
