from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import json5
from pydantic import ValidationError

from src.shared.config.dynamic_settings import DynamicSettings
from src.shared.config.ports import SettingsRepositoryPort

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_HEADER_COMMENT = (
    "// Fraetor 動的設定ファイル (JSONC: // や /* */ のコメントを書ける)\n"
    "// 設定画面から保存するとこのファイルは書き直され、コメントは失われる。\n"
)

# キーは入れ子を "." でつないだ設定のパス (例: "stt.mai.locale")
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
    "sound_enabled": "録音の開始・停止時に効果音を鳴らすか",
    "sound_volume": "効果音の音量 (0.0〜1.0)",
    "stt": "音声認識 (STT) の設定。engine で使うエンジンを選ぶ",
    "stt.engine": "使うエンジン (mai / gemini)。次のセッションから反映される",
    "stt.mai": "MAI Transcribe の設定",
    "stt.mai.locale": "言語ロケール",
    "stt.mai.model_name": "モデル名",
    "stt.mai.transcribe_style": (
        "出力スタイル。verbatim はフィラー・言い直しを含む逐語、"
        "clean はフィラーを除去した読みやすい文字起こし"
    ),
    "stt.mai.timeout_sec": "1リクエストのタイムアウト (秒)",
    "stt.gemini": "Vertex AI Gemini Transcribe の設定",
    "stt.gemini.location": "Vertex AI のロケーション (global / us / eu)",
    "stt.gemini.language_code": "言語コード (例: ja-JP)",
    "stt.gemini.timeout_sec": "1リクエストのタイムアウト (秒)",
    "proofread_timeout_sec": "Gemini による校正のタイムアウト (秒)",
    "shutdown_delay_sec": "終了リクエスト受付からプロセス終了までの遅延 (秒)",
    "sse_keepalive_sec": "SSE のキープアライブ送信間隔 (秒)",
}

# 複数項目の関係で検証される制約 (model_validator) は、どの項目が原因か
# 特定できない。違反時は関係する項目をまとめて既定値に戻す。
_CROSS_FIELD_KEYS = ("segment_silence_sec", "silence_timeout_sec")

# 不正項目を1つずつ取り除いて再検証する回数の上限 (無限ループの防止)
_MAX_REPAIR_ROUNDS = 100


def _render_object(
    data: dict[str, Any], indent: int, path: str, lines: list[str]
) -> None:
    pad = "  " * indent
    items = list(data.items())
    for index, (name, value) in enumerate(items):
        key_path = f"{path}.{name}" if path else name
        comment = _FIELD_COMMENTS.get(key_path)
        if comment:
            lines.append(f"{pad}// {comment}")
        separator = "," if index < len(items) - 1 else ""
        if isinstance(value, dict):
            lines.append(f"{pad}{json.dumps(name)}: {{")
            _render_object(value, indent + 1, key_path, lines)
            lines.append(f"{pad}}}{separator}")
        else:
            lines.append(f"{pad}{json.dumps(name)}: {json.dumps(value)}{separator}")


def _render_jsonc(settings: DynamicSettings) -> str:
    """各項目に説明コメントを付けた JSONC 文字列を組み立てる。"""
    lines = [_HEADER_COMMENT + "{"]
    _render_object(settings.model_dump(), 1, "", lines)
    lines.append("}")
    return "\n".join(lines) + "\n"


def _drop_path(raw: dict[str, Any], loc: tuple[int | str, ...]) -> bool:
    """`raw` から `loc` が指す項目を取り除く。取り除けたら True。"""
    node: Any = raw
    for key in loc[:-1]:
        if not isinstance(node, dict) or key not in node:
            return False
        node = node[key]
    if isinstance(node, dict) and loc[-1] in node:
        del node[loc[-1]]
        return True
    return False


def _validate_per_field(raw: Any) -> DynamicSettings:
    """不正・欠落した項目だけを既定値で補って検証する。

    検証違反のたびに、エラーが指す項目を取り除いて再検証する (取り除いた項目は
    既定値になる)。未知のキーは無視される。補った項目は警告ログに出す。
    """
    if not isinstance(raw, dict):
        logger.warning("Dynamic settings is not an object, using defaults")
        return DynamicSettings()
    for _ in range(_MAX_REPAIR_ROUNDS):
        try:
            return DynamicSettings.model_validate(raw)
        except ValidationError as exc:
            progressed = False
            for error in exc.errors():
                loc = error["loc"]
                if loc:
                    dropped = _drop_path(raw, loc)
                    label = ".".join(str(k) for k in loc)
                else:
                    dropped = any(_drop_path(raw, (k,)) for k in _CROSS_FIELD_KEYS)
                    label = "/".join(_CROSS_FIELD_KEYS)
                if dropped:
                    progressed = True
                    logger.warning(
                        "Invalid dynamic setting, using default: %s (%s)",
                        label,
                        error["msg"],
                    )
            if not progressed:
                break
    logger.warning("Could not repair dynamic settings, using defaults")
    return DynamicSettings()


class JsoncSettingsRepository(SettingsRepositoryPort):
    """動的設定を JSONC ファイルへ永続化するリポジトリ。

    現在値はメモリ上に保持し、`get()` はファイル I/O を伴わない。
    ファイル不在時は既定値の雛形を書き出す。パース失敗時は警告ログを出して
    既定値へフォールバックし (起動を止めない)、バリデーション違反は項目単位で
    既定値に補う (他の項目の値は保つ)。
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
        except (ValueError, OSError):
            logger.warning(
                "Failed to load dynamic settings, falling back to defaults: %s",
                self._path,
                exc_info=True,
            )
            return DynamicSettings()
        return _validate_per_field(raw)

    def _write(self, settings: DynamicSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(_render_jsonc(settings), encoding="utf-8")
