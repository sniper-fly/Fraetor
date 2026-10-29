from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.shared.config.dynamic_settings import DynamicSettings, SttSettings
from src.stt_stats.domain.models import SttLatencySample

if TYPE_CHECKING:
    from starlette.testclient import TestClient


def _record(client: TestClient, engine: str, duration: float) -> None:
    client.app.state.summarize_latency_use_case._repository.save(  # type: ignore[attr-defined]
        SttLatencySample(
            recorded_at=datetime.now(UTC),
            engine=engine,
            phase="flush",
            duration_sec=duration,
            audio_duration_sec=2.0,
            succeeded=True,
        )
    )


class TestSttStats:
    def test_returns_summaries_and_current_engine(self, client: TestClient) -> None:
        client.app.state.settings_repository.update(  # type: ignore[attr-defined]
            DynamicSettings(stt=SttSettings(engine="gemini"))
        )
        _record(client, "mai", 2.0)
        _record(client, "mai", 4.0)

        body = client.get("/api/stats/stt?period=today").json()

        assert body["current_engine"] == "gemini"
        [mai] = body["engines"]
        assert mai["engine"] == "mai"
        assert (mai["overall"]["count"], mai["overall"]["mean_sec"]) == (2, 3.0)
        assert [b["label"] for b in mai["bands"]] == ["3秒未満", "3〜10秒", "10秒以上"]

    def test_unknown_period_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/stats/stt?period=year").status_code == 422


class TestSttSchema:
    def test_schema_describes_each_engine_constraints(self, client: TestClient) -> None:
        """設定画面が型・範囲・選択肢を組み立てられるスキーマを返す。"""
        schemas = client.get("/api/settings/stt-schema").json()

        assert set(schemas) == {"mai", "gemini"}
        mai = schemas["mai"]["properties"]
        assert set(mai["transcribe_style"]["enum"]) == {"clean", "verbatim"}
        assert mai["timeout_sec"]["exclusiveMinimum"] == 0
        assert set(schemas["gemini"]["properties"]["location"]["enum"]) == {
            "global",
            "us",
            "eu",
        }
