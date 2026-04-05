from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.config import HISTORY_DIR, HISTORY_FILE

if TYPE_CHECKING:
    from src.models import Session

logger = logging.getLogger(__name__)


def _session_to_record(session: Session) -> dict[str, Any]:
    """Session を JSONL 1行分の dict に変換する。

    design.md のフォーマット:
    {"id","started_at","ended_at","correction_enabled","timed_out","text","segments"}
    """
    return {
        "id": session.id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "correction_enabled": session.correction_enabled,
        "timed_out": session.timed_out,
        "text": session.full_text,
        "segments": [
            {"raw_text": seg.raw_text, "corrected_text": seg.corrected_text}
            for seg in session.segments
        ],
    }


def save_session(session: Session) -> None:
    """セッションを JSONL ファイルに追記する。"""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    record = _session_to_record(session)
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Session saved to history: %s", session.id)
