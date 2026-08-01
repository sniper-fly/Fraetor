"""E2E テスト用のコンポジションルート。

本番エントリポイント (`src/__main__.py`) と同じ起動手順を踏むが、
`AudioCapturePort` だけ `FRAETOR_AUDIO_FILE` 環境変数で指定した WAV ファイルを
読み込む `FileAudioCapture` に差し替える。実マイクデバイスに依存せずに
`create_app()` 以降の実サーバー・実HTTP API・実SSEを検証するために使う。
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_AUDIO_FILE = "FRAETOR_AUDIO_FILE"


def main() -> None:
    load_dotenv(_PROJECT_ROOT / ".env")

    wav_path_str = os.environ.get(_ENV_AUDIO_FILE)
    if not wav_path_str:
        msg = f"{_ENV_AUDIO_FILE} 環境変数が未設定です。"
        raise RuntimeError(msg)

    from src.containers import Container  # noqa: PLC0415
    from src.dictation.infrastructure.audio.file_capture import (  # noqa: PLC0415
        FileAudioCapture,
    )
    from src.presentation.app import create_app  # noqa: PLC0415

    settings = Container().settings()
    app = create_app(
        audio_capture=FileAudioCapture(
            Path(wav_path_str), sample_rate=settings.stt_sample_rate
        )
    )
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    main()
