from __future__ import annotations

from typing import TYPE_CHECKING

from src.shared.config.dynamic_settings import DynamicSettings

if TYPE_CHECKING:
    from starlette.testclient import TestClient

    from src.shared.config.ports import SettingsRepositoryPort


def _valid_payload(**overrides: object) -> dict[str, object]:
    """全項目を含む正常なリクエストボディを組み立てる。

    PUT は部分更新ではなく全項目の差し替えなので、テスト側も全項目を送る。
    """
    return DynamicSettings().model_dump() | overrides


class TestGetSettings:
    def test_returns_current_values(self, client: TestClient) -> None:
        repo: SettingsRepositoryPort = client.app.state.settings_repository  # type: ignore[attr-defined]
        repo.update(DynamicSettings(segment_silence_sec=4.5, mai_locale="en"))

        response = client.get("/api/settings")

        assert response.status_code == 200
        body = response.json()
        assert body["segment_silence_sec"] == 4.5
        assert body["mai_locale"] == "en"

    def test_returns_all_fields(self, client: TestClient) -> None:
        """UI がフォームを組み立てられるよう、全項目を欠落なく返す。"""
        response = client.get("/api/settings")

        assert set(response.json()) == set(DynamicSettings.model_fields)


class TestUpdateSettings:
    def test_updated_values_are_visible_in_subsequent_get(
        self, client: TestClient
    ) -> None:
        response = client.put(
            "/api/settings", json=_valid_payload(segment_silence_sec=2.0)
        )

        assert response.status_code == 200
        assert response.json()["segment_silence_sec"] == 2.0
        assert client.get("/api/settings").json()["segment_silence_sec"] == 2.0

    def test_update_is_persisted_through_repository(self, client: TestClient) -> None:
        """ルートは自前で状態を持たず、リポジトリへ委譲する。"""
        repo: SettingsRepositoryPort = client.app.state.settings_repository  # type: ignore[attr-defined]

        client.put("/api/settings", json=_valid_payload(vad_threshold=0.8))

        assert repo.get().vad_threshold == 0.8

    def test_silence_threshold_inversion_returns_422(self, client: TestClient) -> None:
        """`segment_silence_sec >= silence_timeout_sec` は 422 で弾く。

        プロジェクト固有のクロスフィールド制約なので、`model_validator` の
        違反が 500 ではなく 422 として返ることを明示的に確認する。
        """
        response = client.put(
            "/api/settings",
            json=_valid_payload(segment_silence_sec=10.0, silence_timeout_sec=5),
        )

        assert response.status_code == 422

    def test_out_of_range_value_returns_422(self, client: TestClient) -> None:
        response = client.put("/api/settings", json=_valid_payload(vad_threshold=1.5))

        assert response.status_code == 422

    def test_rejected_update_does_not_change_current_values(
        self, client: TestClient
    ) -> None:
        """422 で弾いた場合は既存値を書き換えない (部分適用しない)。"""
        repo: SettingsRepositoryPort = client.app.state.settings_repository  # type: ignore[attr-defined]
        before = repo.get()

        client.put(
            "/api/settings",
            json=_valid_payload(segment_silence_sec=10.0, silence_timeout_sec=5),
        )

        assert repo.get() == before

    def test_omitted_field_falls_back_to_default_not_current_value(
        self, client: TestClient
    ) -> None:
        """欠落したフィールドは現在値ではなく既定値になる (部分更新ではない)。

        `DynamicSettings` を全項目に既定値を持つ1つのモデルとして
        リクエストボディに直接使う設計 (プラン §7.1) の帰結。UI は常に
        全項目を送るため実害はないが、暗黙のリセットが起きる点は
        API の契約として明示しておく。
        """
        client.put("/api/settings", json=_valid_payload(mai_locale="en"))
        payload = _valid_payload(segment_silence_sec=2.0)
        del payload["mai_locale"]

        response = client.put("/api/settings", json=payload)

        assert response.status_code == 200
        assert response.json()["mai_locale"] == "ja", "現在値 'en' ではなく既定値に戻る"
