from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.config import HISTORY_DIR, HISTORY_FILE

if TYPE_CHECKING:
    from src.models import Session

logger = logging.getLogger(__name__)


def _session_to_record(session: Session) -> dict[str, Any]:
    """Session を JSONL 1行分の dict に変換する。"""
    return {
        "id": session.id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "timed_out": session.timed_out,
        "text": session.full_text,
        "segments": [{"text": seg.text} for seg in session.segments],
    }


def save_session(session: Session, *, text_override: str | None = None) -> None:
    """セッションを JSONL ファイルに追記する。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    record = _session_to_record(session)
    if text_override is not None:
        record["text"] = text_override
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Session saved to history: %s", session.id)


def delete_session(session_id: str) -> bool:
    """指定されたIDのセッションをJSONLファイルから削除する。"""
    if not HISTORY_FILE.exists():
        return False
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    remaining = [
        line for line in lines if line.strip() and json.loads(line)["id"] != session_id
    ]
    original_count = sum(1 for line in lines if line.strip())
    if len(remaining) == original_count:
        return False
    HISTORY_FILE.write_text(
        "".join(line + "\n" for line in remaining),
        encoding="utf-8",
    )
    logger.info("Session deleted from history: %s", session_id)
    return True
