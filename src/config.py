import json
import subprocess
from pathlib import Path
from typing import Any

# --- セッション ---
MAX_SESSION_DURATION_SEC: int = 180

# --- Azure STT ---
STABLE_PARTIAL_RESULT_THRESHOLD: int = 3
AZURE_REGION: str = "japaneast"
AZURE_LANGUAGE: str = "ja-JP"
STT_SAMPLE_RATE: int = 16000

# --- サーバー ---
SERVER_HOST: str = "127.0.0.1"
SERVER_PORT: int = 8765

# --- SSE ---
SSE_KEEPALIVE_SEC: int = 15

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
AZURE_SPEECH_KEY: str = ""
VERTEX_SA_INFO: dict[str, Any] = {}
VERTEX_PROJECT: str = ""

# --- pass エントリパス ---
_PASS_ENTRY_AZURE: str = "api/azure_stt_key"  # noqa: S105
_PASS_ENTRY_VERTEX_SA: str = "gc/ai_service_account"  # noqa: S105


def _read_pass(entry: str) -> str:
    """passコマンドからシークレットを取得する。"""
    result = subprocess.run(  # noqa: S603
        ["pass", "show", entry],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"pass show {entry} に失敗しました: {result.stderr.strip()}"
        raise RuntimeError(msg)
    return result.stdout.strip()


def init_secrets() -> None:
    """passコマンドからAPIキーを取得し、モジュール変数に設定する。"""
    global AZURE_SPEECH_KEY, VERTEX_SA_INFO, VERTEX_PROJECT  # noqa: PLW0603
    AZURE_SPEECH_KEY = _read_pass(_PASS_ENTRY_AZURE)

    sa_json = _read_pass(_PASS_ENTRY_VERTEX_SA)
    VERTEX_SA_INFO = json.loads(sa_json)
    VERTEX_PROJECT = str(VERTEX_SA_INFO.get("project_id", ""))


def validate_api_keys() -> list[str]:
    """APIキーの設定状態を確認し、警告メッセージのリストを返す。"""
    warnings: list[str] = []
    if not AZURE_SPEECH_KEY:
        warnings.append("AZURE_SPEECH_KEY が未設定です。音声認識は利用できません。")
    if not VERTEX_SA_INFO:
        warnings.append("VERTEX_SA_INFO が未設定です。テキスト校正は利用できません。")
    return warnings


# --- 履歴 ---
HISTORY_DIR: Path = Path("~/.voice-input").expanduser()
HISTORY_FILE: Path = HISTORY_DIR / "history.jsonl"
