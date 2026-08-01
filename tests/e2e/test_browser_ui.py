"""ブラウザUI (Playwright) 経由のE2Eテスト。

実サーバー・実ブラウザ (Chromium) を使い、SSE受信→textarea更新→
履歴タブ操作までの一連のUI動作を検証する。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from collections.abc import Callable

    from playwright.sync_api import Page

_UI_WAIT_MS = 30_000  # Playwright の待機はミリ秒単位
_SESSION_END_WAIT_SEC = 30.0


class TestBrowserUi:
    def test_recording_toggle_updates_textarea_via_sse(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 録音開始→SSE recognized受信→textarea反映→再トグルで停止表示"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")
        page.goto(base_url)

        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '録音中'",
            timeout=_UI_WAIT_MS,
        )

        textarea = page.locator("#editor-textarea")
        page.wait_for_function(
            "document.getElementById('editor-textarea').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        assert "トグル" in textarea.input_value()

        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '停止中'",
            timeout=_UI_WAIT_MS,
        )

    def test_history_delete_button_removes_card(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 履歴タブの削除ボタン押下→一覧から消える"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")
        _run_one_session_and_finalize(base_url)

        page.goto(base_url)
        page.locator("#tab-history").click()
        history_list = page.locator("#history-list")
        delete_button_selector = "[onclick^='deleteHistory']"
        page.wait_for_function(
            f'document.querySelectorAll("{delete_button_selector}").length > 0'
        )
        assert history_list.locator("button", has_text="削除").count() >= 1

        history_list.locator("button", has_text="削除").first.click()
        page.wait_for_function(
            f'document.querySelectorAll("{delete_button_selector}").length === 0'
        )


def _run_one_session_and_finalize(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=None) as client:
        client.post("/api/toggle-recording")

        deadline = time.monotonic() + _SESSION_END_WAIT_SEC
        with client.stream("GET", "/events") as sse_response:
            for line in sse_response.iter_lines():
                if time.monotonic() > deadline:
                    msg = "session_end イベントが届かなかった"
                    raise TimeoutError(msg)
                if line.strip() == "event: session_end":
                    break

        client.post("/api/finalize-session", json={"text": "履歴削除確認用"})
