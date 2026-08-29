from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.shared.config.dynamic_settings import DynamicSettings

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
        assert "設定" in html
        assert "録音" in html
        assert "tailwindcss" in html


# 撮影の有無をサーバー側で判断する必要があるため、汎用フォームではなく
# 専用トグルボタンで操作する設計 (docs/current/spec.md 参照)。
_FORM_EXCLUDED_FIELDS = {"intent_translation_enabled"}


class TestSettingsTabMarkup:
    """設定タブの JS 側定義とサーバー側モデルの整合を検証する。

    `SETTINGS_FIELDS` と `DynamicSettings` は同じ項目一覧を別の場所で
    持つため、片方だけ増減すると「入力欄がない項目が既定値へ静かに戻る」
    (`tests/.../test_settings_routes.py` の
    `test_omitted_field_falls_back_to_default_not_current_value` 参照)
    という形で壊れる。ブラウザを起動しなくても検出できるようにする。
    """

    def test_settings_fields_cover_all_dynamic_settings(
        self, client: TestClient
    ) -> None:
        html = client.get("/").text
        js_keys = set(re.findall(r"\{ key: '(\w+)'", html))
        expected = set(DynamicSettings.model_fields) - _FORM_EXCLUDED_FIELDS

        assert js_keys == expected

    def test_every_tab_has_matching_button_and_panel(self, client: TestClient) -> None:
        """`TABS` の各キーに対応する `tab-*`/`panel-*` 要素が存在する。

        `switchTab` は `TABS` のキーから DOM id を組み立てるため、要素名が
        欠けるとタブ切り替え全体が例外で止まる。
        """
        html = client.get("/").text
        tabs_literal = re.search(r"const TABS = \{(.+?)\};", html, re.DOTALL)
        assert tabs_literal is not None
        tab_names = re.findall(r"(\w+):", tabs_literal.group(1))

        assert set(tab_names) == {"main", "history", "settings"}
        for name in tab_names:
            assert f'id="tab-{name}"' in html
            assert f'id="panel-{name}"' in html
