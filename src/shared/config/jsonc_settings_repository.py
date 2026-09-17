from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import json5

from src.shared.config.dynamic_settings import DynamicSettings
from src.shared.config.ports import SettingsRepositoryPort

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_HEADER_COMMENT = (
    "// Fraetor 動的設定ファイル (JSONC: // や /* */ のコメントを書ける)\n"
    "// 設定画面から保存するとこのファイルは書き直され、コメントは失われる。\n"
)

_FIELD_COMMENTS = {
    "max_session_duration_sec": (
        "1セッションの最大録音時間 (秒)。超過すると強制終了する"
    ),
    "silence_timeout_sec": "無音が続いた場合にセッションを終了するまでの時間 (秒)",
    "segment_silence_sec": (
        "無音がこの秒数続いたら、そこまでの発話を1セグメントとして"
        "文字起こしに送る。silence_timeout_sec より小さい必要がある"
    ),
    "vad_threshold": "発話区間検出の閾値 (0.0〜1.0)。小さいほど発話と判定しやすい",
    "mai_locale": "MAI Transcribe に指定する言語ロケール",
    "mai_model_name": "MAI Transcribe のモデル名",
    "mai_transcribe_style": (
        "MAI Transcribe の出力スタイル。verbatim はフィラー・言い直しを含む逐語、"
        "clean はフィラーを除去した読みやすい文字起こし"
    ),
    "mai_timeout_sec": "MAI Transcribe への1リクエストのタイムアウト (秒)",
    "proofread_timeout_sec": "Gemini による校正のタイムアウト (秒)",
    "shutdown_delay_sec": "終了リクエスト受付からプロセス終了までの遅延 (秒)",
    "sse_keepalive_sec": "SSE のキープアライブ送信間隔 (秒)",
}


def _render_jsonc(settings: DynamicSettings) -> str:
    """各項目に説明コメントを付けた JSONC 文字列を組み立てる。"""
    lines = [_HEADER_COMMENT + "{"]
    fields = list(DynamicSettings.model_fields)
    dumped = settings.model_dump()
    for index, name in enumerate(fields):
        comment = _FIELD_COMMENTS.get(name)
        if comment:
            lines.append(f"  // {comment}")
        separator = "," if index < len(fields) - 1 else ""
        lines.append(f"  {json.dumps(name)}: {json.dumps(dumped[name])}{separator}")
    lines.append("}")
    return "\n".join(lines) + "\n"


class JsoncSettingsRepository(SettingsRepositoryPort):
    """動的設定を JSONC ファイルへ永続化するリポジトリ。

    現在値はメモリ上に保持し、`get()` はファイル I/O を伴わない。
    ファイル不在時は既定値の雛形を書き出し、パース失敗・バリデーション
    違反時は警告ログを出して既定値へフォールバックする (起動を止めない)。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._current = self._load_or_create()

    def get(self) -> DynamicSettings:
        return self._current

    def update(self, new_settings: DynamicSettings) -> None:
        self._write(new_settings)
        self._current = new_settings
        logger.info("Dynamic settings updated: %s", self._path)

    def _load_or_create(self) -> DynamicSettings:
        if not self._path.exists():
            defaults = DynamicSettings()
            self._write(defaults)
            logger.info("Dynamic settings file created: %s", self._path)
            return defaults
        try:
            raw = json5.loads(self._path.read_text(encoding="utf-8"))
            # ValidationError は ValueError の派生なのでここで一緒に捕まる
            return DynamicSettings.model_validate(raw)
        except (ValueError, OSError):
            logger.warning(
                "Failed to load dynamic settings, falling back to defaults: %s",
                self._path,
                exc_info=True,
            )
            return DynamicSettings()

    def _write(self, settings: DynamicSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(_render_jsonc(settings), encoding="utf-8")
