"""ブラウザUI (Playwright) 経由のE2Eテスト。

実サーバー・実ブラウザ (Chromium) を使い、SSE受信→textarea更新→
履歴タブ操作までの一連のUI動作を検証する。
"""

from __future__ import annotations

import json
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

        session_id = page.evaluate("sessionQueue[sessionQueue.length - 1].id")
        textarea = page.locator(f"#block-textarea-{session_id}")
        page.wait_for_function(
            f"document.getElementById('block-textarea-{session_id}').value.length > 0",
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

    def test_main_copy_button_copies_textarea_content(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: メイン画面のコピーボタン押下でtextareaの内容がクリップボードに渡る。

        ヘッドレス環境では `navigator.clipboard` へのOS権限が不安定なため、
        `writeText` を差し替えて呼び出し引数を記録する方式で検証する。
        """
        page.add_init_script(
            "window.__clipboardWrites = [];"
            " navigator.clipboard.writeText ="
            " (t) => { window.__clipboardWrites.push(t); return Promise.resolve(); };"
        )
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")
        page.goto(base_url)

        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function("sessionQueue.length > 0", timeout=_UI_WAIT_MS)
        session_id = page.evaluate("sessionQueue[sessionQueue.length - 1].id")
        page.wait_for_function(
            f"document.getElementById('block-textarea-{session_id}').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        expected_text = page.locator(f"#block-textarea-{session_id}").input_value()

        page.locator("#btn-copy-main").click()

        writes = page.evaluate("window.__clipboardWrites")
        assert writes == [expected_text]
        toast = page.locator("#copy-toast")
        page.wait_for_function(
            "!document.getElementById('copy-toast').classList.contains('opacity-0')"
        )
        assert toast.inner_text().strip() == "コピーしました"

    def test_history_card_click_copies_text_without_triggering_on_delete(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 履歴カードクリックでコピーされ、削除ボタンではコピーされない"""
        page.add_init_script(
            "window.__clipboardWrites = [];"
            " navigator.clipboard.writeText ="
            " (t) => { window.__clipboardWrites.push(t); return Promise.resolve(); };"
        )
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")
        _run_one_session_and_finalize(base_url)

        page.goto(base_url)
        page.locator("#tab-history").click()
        history_list = page.locator("#history-list")
        page.wait_for_function(
            "document.querySelectorAll(\"[onclick^='deleteHistory']\").length > 0"
        )

        card = history_list.locator("div.bg-gray-800").first
        expected_text = card.locator("div.text-sm").inner_text()
        card.click()
        assert page.evaluate("window.__clipboardWrites") == [expected_text]
        page.wait_for_function(
            "!document.getElementById('copy-toast').classList.contains('opacity-0')"
        )

        history_list.locator("button", has_text="削除").first.click()
        assert page.evaluate("window.__clipboardWrites") == [expected_text]

    def test_two_consecutive_recordings_do_not_mix_across_blocks(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 録音A→確定完了→録音Bと直列で行った場合、
        (1) Aのブロックは確定後もDOM上に残り続け (複数ブロック同時表示)、
        (2) Bはセッションごとに独立した別のブロック要素として生成され、
        (3) Bのブロックの内容にAの文字列が混入しない
        ことを検証する (ブロックがセッションIDごとに独立したDOM要素であり、
        単一要素を使い回さないことの回帰テスト)。
        """
        base_url = fraetor_server_with_audio("04_short_utterance.wav")
        page.goto(base_url)

        # 録音A: トグルON→(無音タイムアウトより先に)OFF
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '録音中'",
            timeout=_UI_WAIT_MS,
        )
        session_id_a = page.evaluate("sessionQueue[sessionQueue.length - 1].id")
        page.wait_for_timeout(2000)
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '停止中'",
            timeout=_UI_WAIT_MS,
        )

        textarea_a_id = f"block-textarea-{session_id_a}"
        page.wait_for_function(
            f"document.getElementById('{textarea_a_id}').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        text_after_a = page.locator(f"#{textarea_a_id}").input_value()
        assert text_after_a.strip(), "録音Aの結果が表示されなかった"

        # 確定 (finalize-session) 処理が完了するまで待つ
        page.wait_for_function(
            f"sessionQueue.find(s => s.id === '{session_id_a}')?.finalized === true",
            timeout=_UI_WAIT_MS,
        )

        # 録音B: 同じ音声を再度録音し、Aとは別のブロックが生成されることを確認する
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '録音中'",
            timeout=_UI_WAIT_MS,
        )
        page.wait_for_function(
            "sessionQueue.length > 0"
            f" && sessionQueue[sessionQueue.length - 1].id !== '{session_id_a}'",
            timeout=_UI_WAIT_MS,
        )
        session_id_b = page.evaluate("sessionQueue[sessionQueue.length - 1].id")
        assert session_id_b != session_id_a, "Bが新しいブロックとして生成されなかった"
        # Aのブロックは確定後もDOM上に残り、内容が保持され続ける (複数ブロック表示)。
        assert page.locator(f"#block-{session_id_a}").count() == 1, (
            "確定済みのAのブロックが録音B開始時に消えている"
        )

        page.wait_for_timeout(2000)
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '停止中'",
            timeout=_UI_WAIT_MS,
        )

        textarea_b_id = f"block-textarea-{session_id_b}"
        page.wait_for_function(
            f"document.getElementById('{textarea_b_id}').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        text_after_b = page.locator(f"#{textarea_b_id}").input_value()

        assert text_after_b.strip(), "録音Bの結果が表示されなかった"
        # 同一音声ファイルのため認識結果は同一になり得るが、Aの文字列がBの
        # ブロックに継ぎ足されていれば重複して出現するため、出現回数で検出する
        # (「含んでいない」ことではなく「二重に含まれていない」ことを検証する)。
        assert text_after_b.count(text_after_a.strip()[:5]) <= 1, (
            "Bのブロックに前セッションの内容が継ぎ足されている"
        )


def _run_one_session_and_finalize(base_url: str) -> None:
    with httpx.Client(base_url=base_url, timeout=None) as client:
        client.post("/api/toggle-recording")

        session_id = None
        deadline = time.monotonic() + _SESSION_END_WAIT_SEC
        with client.stream("GET", "/events") as sse_response:
            event_type = None
            for line in sse_response.iter_lines():
                if time.monotonic() > deadline:
                    msg = "session_end イベントが届かなかった"
                    raise TimeoutError(msg)
                if line.startswith("event: "):
                    event_type = line.removeprefix("event: ").strip()
                elif line.startswith("data: ") and event_type == "session_end":
                    session_id = json.loads(line.removeprefix("data: "))["session_id"]
                    break

        client.post(
            "/api/finalize-session",
            json={"session_id": session_id, "text": "履歴削除確認用"},
        )
