"""E2E テスト共通のヘルパー関数 (fixture ではなく通常のユーティリティ)。"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    import httpx


def play_audio_into_sink(sink_name: str, wav_path: Path) -> subprocess.Popen[bytes]:
    """指定した null-sink へ WAV ファイルを再生するプロセスを起動する。"""
    return subprocess.Popen(
        ["/usr/bin/paplay", f"--device={sink_name}", str(wav_path)],
    )


async def iter_sse_events(
    response: httpx.Response,
) -> AsyncIterator[dict[str, str]]:
    """`sse_starlette` が送出する SSE ストリームを 1 イベントずつ辞書で返す。

    `ServerSentEvent.encode()` の出力形式 (フィールド行の後に空行で
    区切り) に合わせた最小限のパーサ。
    """
    event_type = "message"
    data_lines: list[str] = []
    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r")
        if line == "":
            if data_lines:
                yield {"event": event_type, "data": "\n".join(data_lines)}
            event_type = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event_type = value
        elif field == "data":
            data_lines.append(value)
