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
from fastapi import APIRouter, Request

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_AUDIO_FILE = "FRAETOR_AUDIO_FILE"
_AUDIO_DIR = Path(__file__).parent / "fixtures" / "audio"

_test_router = APIRouter()


@_test_router.post("/api/_test/switch-audio")
async def switch_audio(request: Request) -> dict[str, bool]:
    """次回録音で読み込むWAVファイルを切り替える (E2E専用、本番には存在しない)。"""
    body = await request.json()
    wav_filename = body["wav_filename"]
    request.app.state.file_audio_capture.set_wav_path(_AUDIO_DIR / wav_filename)
    return {"ok": True}


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
    audio_capture = FileAudioCapture(
        Path(wav_path_str), sample_rate=settings.stt_sample_rate
    )
    app = create_app(audio_capture=audio_capture)
    app.state.file_audio_capture = audio_capture
    app.include_router(_test_router)
    uvicorn.run(app, host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    main()
