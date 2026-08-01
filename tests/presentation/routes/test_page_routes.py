from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.testclient import TestClient


class TestIndex:
    def test_serves_browser_ui(self, client: TestClient) -> None:
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        html = response.text
        assert "メイン" in html
        assert "履歴" in html
        assert "録音" in html
        assert "tailwindcss" in html
