import subprocess
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

# --- シークレット (init_secrets() で設定) ---
AZURE_SPEECH_KEY: str = ""
GEMINI_API_KEY: str = ""

# --- pass エントリパス ---
_PASS_ENTRIES: dict[str, str] = {
    "AZURE_SPEECH_KEY": "api/azure_stt_key",
    "GEMINI_API_KEY": "api/gemini",
}


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
    global AZURE_SPEECH_KEY, GEMINI_API_KEY  # noqa: PLW0603
    AZURE_SPEECH_KEY = _read_pass(_PASS_ENTRIES["AZURE_SPEECH_KEY"])
    GEMINI_API_KEY = _read_pass(_PASS_ENTRIES["GEMINI_API_KEY"])


# --- Gemini ---
GEMINI_MODEL: str = "gemini-3.1-flash-live-preview"
CORRECTION_PROMPT: str = (
    "音声認識で得られたテキストを校正してください。\n"
    "- 句読点・記号を適切に追加・修正する\n"
    "- 誤字脱字を修正する\n"
    "- 不自然な表現を自然な日本語に修正する\n"
    "- 文脈を考慮して自然な文章にする\n"
    "- 校正結果のテキストのみを返す(説明や補足は一切付けない)"
)


def validate_api_keys() -> list[str]:
    """APIキーの設定状態を確認し、警告メッセージのリストを返す。"""
    warnings: list[str] = []
    if not AZURE_SPEECH_KEY:
        warnings.append("AZURE_SPEECH_KEY が未設定です。音声認識は利用できません。")
    if not GEMINI_API_KEY:
        warnings.append("GEMINI_API_KEY が未設定です。校正機能は利用できません。")
    return warnings


# --- 履歴 ---
HISTORY_DIR: Path = Path("~/.voice-input").expanduser()
HISTORY_FILE: Path = HISTORY_DIR / "history.jsonl"
