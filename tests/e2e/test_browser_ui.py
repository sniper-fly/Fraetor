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
        page.wait_for_function(
            "document.getElementById('editor-textarea').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        expected_text = page.locator("#editor-textarea").input_value()

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

    def test_two_consecutive_recordings_do_not_mix_in_textarea(
        self, page: Page, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 録音A→確定完了→録音Bと直列で行った場合、
        (1) 確定 (finalize-session) 完了後もAの内容がtextareaに残り続け、
        (2) 次の録音B開始時に初めてtextareaがクリアされ、
        (3) Bのtextareaの内容にAの文字列が混入しない
        ことを検証する (textareaの継ぎ足しバグ・過早クリアバグの回帰テスト)。

        (1) は「確定直後にtextareaが一瞬だけ空になって消える」という
        バグを検出する必要があるが、テスト側から `fetch('/api/history')`
        等の別リクエストでポーリングして完了を判定する方式では、ブラウザの
        HTTPリクエストがイベントループの別タスクとして解決されるため、
        `tryAdvanceQueue()` 内で `sessionQueue.shift()` の直前に実行される
        `textarea.value = ''`(バグ再現時)を必ず追い越せてしまい、
        バグを見逃す (実際に検証済み: ポーリング方式ではバグを意図的に
        再現させてもテストが誤ってPASSした)。そのため `page.add_init_script`
        で `textarea.value` の setter を差し替え、代入された値の履歴を
        `window.__textareaValueLog` に全件記録した上で、`tryAdvanceQueue()`
        が確定処理を終える際に必ず変化する `sessionQueue.length === 0`
        (キューからの除去はfinalize完了後、次のクリア候補の代入より前に
        同期的に実行される) を完了シグナルとして待つ。
        """
        page.add_init_script(
            """
            window.__textareaValueLog = [];
            document.addEventListener('DOMContentLoaded', () => {
              const el = document.getElementById('editor-textarea');
              const descriptor = Object.getOwnPropertyDescriptor(
                HTMLTextAreaElement.prototype, 'value'
              );
              Object.defineProperty(el, 'value', {
                configurable: true,
                get() { return descriptor.get.call(this); },
                set(v) {
                  window.__textareaValueLog.push(v);
                  return descriptor.set.call(this, v);
                }
              });
            });
            """
        )
        base_url = fraetor_server_with_audio("04_short_utterance.wav")
        page.goto(base_url)

        # 録音A: トグルON→(無音タイムアウトより先に)OFF
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '録音中'",
            timeout=_UI_WAIT_MS,
        )
        page.wait_for_timeout(2000)
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '停止中'",
            timeout=_UI_WAIT_MS,
        )

        page.wait_for_function(
            "document.getElementById('editor-textarea').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        text_after_a = page.locator("#editor-textarea").input_value()
        assert text_after_a.strip(), "録音Aの結果が表示されなかった"
        log_len_after_a_shown = page.evaluate("window.__textareaValueLog.length")

        # 確定 (finalize-session) 処理が完了するまで待つ。
        # sessionQueue.shift() は finalize-session 完了直後、かつ
        # (バグ再現時の) textarea.value = '' の直後に同期実行されるため、
        # sessionQueue.length === 0 への遷移を確実な完了シグナルにできる
        # (/api/history 等の別リクエストによるポーリングでは、ブラウザの
        # 同期的なJS実行順序を確実に追い越せずバグを見逃す)。
        page.wait_for_function("sessionQueue.length === 0", timeout=_UI_WAIT_MS)
        # 回帰テスト: Aが表示されてからfinalize完了までの間に、textareaへ
        # 空文字列が代入された瞬間が一度でもあれば、確定直後にtextareaが
        # 一瞬クリアされて消えるバグが再発している。
        log_since_a_shown = page.evaluate(
            f"window.__textareaValueLog.slice({log_len_after_a_shown})"
        )
        assert "" not in log_since_a_shown, (
            "finalize完了までの間にtextareaが一瞬空になった"
            " (次の録音が始まる前に消えるバグ)"
        )

        # 録音B: 同じ音声を再度録音し、Aの文字列が残っていないことを確認する
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '録音中'",
            timeout=_UI_WAIT_MS,
        )
        # 録音B開始時に初めてtextareaがクリアされ、Aの内容が消えるべき。
        page.wait_for_function(
            "document.getElementById('editor-textarea').value === ''",
            timeout=_UI_WAIT_MS,
        )
        page.wait_for_timeout(2000)
        page.evaluate("fetch('/api/toggle-recording', {method: 'POST'})")
        page.wait_for_function(
            "document.getElementById('rec-label').textContent === '停止中'",
            timeout=_UI_WAIT_MS,
        )

        page.wait_for_function(
            "document.getElementById('editor-textarea').value.length > 0",
            timeout=_UI_WAIT_MS,
        )
        text_after_b = page.locator("#editor-textarea").input_value()

        assert text_after_b.strip(), "録音Bの結果が表示されなかった"
        # Bの内容はAの内容を「含んでいない」(継ぎ足しが起きていない) ことを確認する。
        # 同一音声ファイルのため認識結果は概ね同一だが、Aの文字列がBの前方に
        # 重複して残っていれば len が異常に長くなる/文字列が2回出現するため検出できる
        assert text_after_b.count(text_after_a.strip()[:5]) <= 1, (
            "textareaに前セッションの内容が継ぎ足されている"
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
