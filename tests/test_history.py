from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.history import delete_session, save_session
from src.models import Segment, Session

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _make_session(
    *,
    timed_out: bool = False,
    segments: list[Segment] | None = None,
) -> Session:
    if segments is None:
        segments = [
            Segment(id=0, text="校正済み。"),
        ]
    return Session(
        id="test-session-id",
        segments=segments,
        started_at=datetime(2026, 4, 4, 14, 28, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 4, 14, 28, 15, tzinfo=UTC),
        timed_out=timed_out,
    )


class TestSaveSession:
    def test_creates_directory_and_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """HISTORY_DIR が存在しない場合でもディレクトリを作成して保存する"""
        history_dir = tmp_path / "new_dir"
        history_file = history_dir / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", history_dir)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session())

        assert history_file.exists()

    def test_record_matches_design_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """azure-stt-only-spec.md: JSONL フォーマットに準拠したレコードが保存される"""
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session())

        record = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert record["id"] == "test-session-id"
        assert record["started_at"] == "2026-04-04T14:28:00+00:00"
        assert record["ended_at"] == "2026-04-04T14:28:15+00:00"
        assert record["timed_out"] is False
        assert record["text"] == "校正済み。"
        assert record["segments"] == [{"text": "校正済み。"}]

    def test_appends_multiple_sessions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """azure-stt-only-spec.md: セッション終了時に JSONL に追記"""
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session())
        save_session(_make_session(timed_out=True))

        lines = history_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["timed_out"] is False
        assert json.loads(lines[1])["timed_out"] is True

    def test_multiple_segments_concatenated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """azure-stt-only-spec.md: 全セグメントのテキスト結合"""
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        session = _make_session(
            segments=[
                Segment(id=0, text="資料を準備しておいてください。"),
                Segment(id=1, text="よろしくお願いします。"),
            ],
        )
        save_session(session)

        record = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert record["text"] == "資料を準備しておいてください。よろしくお願いします。"
        assert len(record["segments"]) == 2

    def test_timed_out_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session(timed_out=True))

        record = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert record["timed_out"] is True

    def test_text_override_used_when_provided(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """text_override 指定時に text フィールドがオーバーライドされること"""
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session(), text_override="edited text")

        record = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert record["text"] == "edited text"

    def test_segments_preserved_with_text_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """text_override 使用時も segments は変わらないこと"""
        history_file = tmp_path / "history.jsonl"
        monkeypatch.setattr("src.history.HISTORY_DIR", tmp_path)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        save_session(_make_session(), text_override="edited text")

        record = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert record["segments"] == [{"text": "校正済み。"}]


class TestDeleteSession:
    def _write_jsonl(self, path: Path, records: list[dict[str, object]]) -> None:
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )

    def test_deletes_matching_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """3件中1件を削除し、残り2件が正しく残る"""
        history_file = tmp_path / "history.jsonl"
        records: list[dict[str, object]] = [
            {"id": "a", "text": "first"},
            {"id": "b", "text": "second"},
            {"id": "c", "text": "third"},
        ]
        self._write_jsonl(history_file, records)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        result = delete_session("b")

        assert result is True
        lines = history_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        ids = [json.loads(line)["id"] for line in lines]
        assert ids == ["a", "c"]

    def test_returns_false_when_id_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """存在しないIDを指定した場合に False を返しファイル内容不変"""
        history_file = tmp_path / "history.jsonl"
        records: list[dict[str, object]] = [{"id": "a", "text": "first"}]
        self._write_jsonl(history_file, records)
        original_content = history_file.read_text(encoding="utf-8")
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        result = delete_session("nonexistent")

        assert result is False
        assert history_file.read_text(encoding="utf-8") == original_content

    def test_returns_false_when_file_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ファイルが存在しない場合に False を返す"""
        history_file = tmp_path / "nonexistent.jsonl"
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        result = delete_session("any-id")

        assert result is False

    def test_preserves_other_records(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """削除後、他のレコードの内容が変化していない"""
        history_file = tmp_path / "history.jsonl"
        records: list[dict[str, object]] = [
            {"id": "a", "text": "first", "extra": 42},
            {"id": "b", "text": "second"},
        ]
        self._write_jsonl(history_file, records)
        monkeypatch.setattr("src.history.HISTORY_FILE", history_file)

        delete_session("b")

        remaining = json.loads(history_file.read_text(encoding="utf-8").strip())
        assert remaining == {"id": "a", "text": "first", "extra": 42}
