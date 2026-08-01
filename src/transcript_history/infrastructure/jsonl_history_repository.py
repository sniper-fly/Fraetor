from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from src.transcript_history.domain.ports import HistoryRepositoryPort

if TYPE_CHECKING:
    from pathlib import Path

    from src.transcript_history.domain.models import FinalizedSession

logger = logging.getLogger(__name__)


def _session_to_record(session: FinalizedSession) -> dict[str, Any]:
    """FinalizedSession を JSONL 1行分の dict に変換する。"""
    return {
        "id": session.id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat(),
        "timed_out": session.timed_out,
        "text": session.full_text,
        "segments": [{"text": seg.text} for seg in session.segments],
    }


class JsonlHistoryRepository(HistoryRepositoryPort):
    """JSONLファイルによるセッション履歴の永続化。"""

    def __init__(self, history_dir: Path) -> None:
        self._history_dir = history_dir
        self._history_file = history_dir / "history.jsonl"

    def save(
        self, session: FinalizedSession, *, text_override: str | None = None
    ) -> None:
        self._history_dir.mkdir(parents=True, exist_ok=True)
        record = _session_to_record(session)
        if text_override is not None:
            record["text"] = text_override
        with self._history_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Session saved to history: %s", session.id)

    def list_all(self) -> list[dict[str, object]]:
        if not self._history_file.exists():
            return []
        text = self._history_file.read_text(encoding="utf-8").strip()
        if not text:
            return []
        sessions: list[dict[str, object]] = [
            json.loads(line) for line in text.splitlines() if line.strip()
        ]
        sessions.reverse()
        return sessions

    def delete(self, session_id: str) -> bool:
        if not self._history_file.exists():
            return False
        lines = self._history_file.read_text(encoding="utf-8").splitlines()
        remaining = [
            line
            for line in lines
            if line.strip() and json.loads(line)["id"] != session_id
        ]
        original_count = sum(1 for line in lines if line.strip())
        if len(remaining) == original_count:
            return False
        self._history_file.write_text(
            "".join(line + "\n" for line in remaining),
            encoding="utf-8",
        )
        logger.info("Session deleted from history: %s", session_id)
        return True
