import os
from pathlib import Path

# --- セッション ---
MAX_SESSION_DURATION_SEC: int = 180
CORRECTION_TIMEOUT_SEC: int = 10

# --- Azure STT ---
STABLE_PARTIAL_RESULT_THRESHOLD: int = 3
AZURE_REGION: str = "japaneast"
AZURE_LANGUAGE: str = "ja-JP"
STT_SAMPLE_RATE: int = 16000

# --- ホットキー ---
HOTKEY_RECORD: str = "KEY_F9"

# --- サーバー ---
SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = 8765

# --- SSE ---
SSE_KEEPALIVE_SEC: int = 15

# --- 環境変数 ---
AZURE_SPEECH_KEY: str = os.environ.get("AZURE_SPEECH_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")

# --- Gemini ---
GEMINI_MODEL: str = "gemini-2.5-flash-preview-native-audio-dialog"

# --- 履歴 ---
HISTORY_DIR: Path = Path("~/.voice-input").expanduser()
HISTORY_FILE: Path = HISTORY_DIR / "history.jsonl"
