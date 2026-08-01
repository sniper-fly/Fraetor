"""E2E テスト用のコンポジションルート。

本番エントリポイント (`src/__main__.py`) と同じ起動手順を踏むが、
`AudioCapture` だけ `FRAETOR_AUDIO_FILE` 環境変数で指定した WAV ファイルを
読み込む `FileAudioCapture` に差し替える。実マイクデバイスに依存せずに
`create_app()` 以降の実サーバー・実HTTP API・実SSEを検証するために使う。
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from src.config import SERVER_HOST, SERVER_PORT, init_secrets

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_AUDIO_FILE = "FRAETOR_AUDIO_FILE"


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")
    init_secrets()

    wav_path_str = os.environ.get(_ENV_AUDIO_FILE)
    if not wav_path_str:
        msg = f"{_ENV_AUDIO_FILE} 環境変数が未設定です。"
        raise RuntimeError(msg)

    # `src.stt_mai` は `src.config` の値をインポート時に束縛するため、
    # 本番の `uvicorn.run("src.app:app", ...)` (文字列経由の遅延インポート)
    # と同じく、`init_secrets()` 実行後にインポートする必要がある。
    from src.app import create_app  # noqa: PLC0415
    from src.audio_file import FileAudioCapture  # noqa: PLC0415

    app = create_app(audio_capture=FileAudioCapture(Path(wav_path_str)))
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)


if __name__ == "__main__":
    main()
