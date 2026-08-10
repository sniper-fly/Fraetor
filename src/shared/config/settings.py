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
    """起動時に確定する静的な定数群。シークレットは含まない
    (secrets_loader.Secrets 参照)。

    実行中に変更できる値は `DynamicSettings` に置く。ここに残すのは
    「変更にプロセス再起動が必要」なもの (TCP bind、Singleton に紐づく
    リソース、データ配置) に限る。
    """

    model_config = ConfigDict(frozen=True)

    # --- STT 共通 (audio_capture Singleton のマイクストリームに紐づく) ---
    stt_sample_rate: int

    # --- サーバー (TCP bind は起動時に確定する) ---
    server_host: str
    server_port: int

    # --- 校正 (Proofreading クライアント Singleton の生成に紐づく) ---
    vertex_location: str
    gemini_model: str
    proofread_prompt: str

    # --- 履歴 (実行中の切り替えはデータ配置の整合性を崩す) ---
    history_dir: Path


def load_settings() -> Settings:
    """環境変数オーバーライドを適用して Settings を構築する。

    環境変数は E2E テストでポート・履歴ファイルを隔離された値に
    変更するためのもの。タイムアウト系は `DynamicSettings`
    (設定ファイル経由) へ移ったため、ここでは扱わない。
    """
    history_dir = Path(
        os.environ.get("FRAETOR_HISTORY_DIR", "~/.voice-input")
    ).expanduser()
    return Settings(
        stt_sample_rate=16000,
        server_host="127.0.0.1",
        server_port=int(os.environ.get("FRAETOR_SERVER_PORT", "8765")),
        vertex_location="global",
        gemini_model="gemini-3.1-flash-lite-preview",
        proofread_prompt=_DEFAULT_PROOFREAD_PROMPT,
        history_dir=history_dir,
    )
