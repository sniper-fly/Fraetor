"""JSONL履歴ファイルへの実ファイルシステム書き込みを検証するE2Eテスト。"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import httpx

from tests.e2e.helpers import iter_sse_events

if TYPE_CHECKING:
    from collections.abc import Callable

    from tests.e2e.conftest import AudioServerHandle

_SESSION_END_WAIT_SEC = 30.0


async def _run_session_and_finalize(base_url: str) -> None:
    """録音開始→session_end待ち→finalize-sessionまで実行する。"""
    async with (
        httpx.AsyncClient(base_url=base_url, timeout=None) as client,
        client.stream("GET", "/events") as sse_response,
    ):
        await client.post("/api/toggle-recording")

        async def wait_for_session_end() -> str:
            async for event in iter_sse_events(sse_response):
                if event["event"] == "session_end":
                    return str(json.loads(event["data"])["session_id"])
            msg = "session_end イベントが届かなかった"
            raise AssertionError(msg)

        session_id = await asyncio.wait_for(
            wait_for_session_end(), timeout=_SESSION_END_WAIT_SEC
        )

    async with httpx.AsyncClient(base_url=base_url) as client:
        await client.post(
            "/api/finalize-session",
            json={"session_id": session_id, "text": "確認用テキスト"},
        )


class TestHistoryFile:
    async def test_consecutive_sessions_appended_in_order(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """正常系: 複数セッションを連続実行し、JSONLに正しい順序で追記される"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")

        await _run_session_and_finalize(base_url)
        await _run_session_and_finalize(base_url)

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.get("/api/history")

        sessions = response.json()
        assert len(sessions) == 2
        # /api/history は新しい順に返すため、ended_at で古い→新しいに並び直す
        ended_ats = [s["ended_at"] for s in sessions]
        assert ended_ats == sorted(ended_ats, reverse=True)

    async def test_delete_nonexistent_session_returns_404(
        self, fraetor_server_with_audio: Callable[[str], str]
    ) -> None:
        """異常系: 存在しないセッションIDの削除リクエストで404"""
        base_url = fraetor_server_with_audio("05_toggle_recording.wav")

        async with httpx.AsyncClient(base_url=base_url) as client:
            response = await client.delete("/api/history/nonexistent-session-id")

        assert response.status_code == 404


class TestOverlappingSessions:
    async def test_overlapping_sessions_are_saved_independently(
        self, fraetor_audio_server_handle: AudioServerHandle
    ) -> None:
        """録音A停止直後(文字起こし未完了)に、異なる発話内容の録音Bを開始しても、
        両セッションのrecognized結果が個別に混ざらず履歴に保存される。"""
        base_url = fraetor_audio_server_handle.start("01_normal_speech.wav")
        session_events: dict[str, list[dict[str, str]]] = {}
        session_ids: list[str] = []

        async with (
            httpx.AsyncClient(base_url=base_url, timeout=None) as client,
            client.stream("GET", "/events") as sse_response,
        ):

            async def collect() -> None:
                async for event in iter_sse_events(sse_response):
                    data = json.loads(event["data"]) if event["data"] else {}
                    sid: str | None = data.get("session_id")
                    if sid:
                        session_events.setdefault(sid, []).append(event)
                    if event["event"] == "session_end" and sid:
                        session_ids.append(sid)
                        if len(session_ids) == 2:
                            return

            # A: トグルON→OFF (文字起こしはTranscriptionQueueにenqueueされ未完了のまま)
            await client.post("/api/toggle-recording")
            await asyncio.sleep(2)  # FileAudioCaptureが音声データを読み込む時間を確保
            await client.post("/api/toggle-recording")
            # Aの文字起こし未完了のうちにBの音声へ切り替えてから開始する
            # (stop_session()は即時returnする実装のため、次のトグルをすぐ発行できる)
            fraetor_audio_server_handle.switch_audio("04_short_utterance.wav")
            await client.post("/api/toggle-recording")  # B: トグルON
            await asyncio.sleep(2)
            await client.post("/api/toggle-recording")  # B: トグルOFF

            await asyncio.wait_for(collect(), timeout=_SESSION_END_WAIT_SEC)

        assert len(set(session_ids)) == 2, "同一session_idが重複していないこと"

        # 各session_idごとに、そのセッション自身のrecognizedイベントだけから
        # 「正解の全文」を組み立てる (厳密な発話内容には依存しない)
        expected_full_texts: dict[str, str] = {}
        for sid, events in session_events.items():
            texts = [
                json.loads(e["data"])["text"]
                for e in events
                if e["event"] == "recognized"
            ]
            expected_full_texts[sid] = "".join(texts)
            print(f"\n[session_id={sid}] 認識結果: {' / '.join(texts) or '(空)'}")

        async with httpx.AsyncClient(base_url=base_url) as client:
            for sid in session_ids:
                await client.post(
                    "/api/finalize-session",
                    json={"session_id": sid, "text": expected_full_texts[sid]},
                )
            response = await client.get("/api/history")

        sessions = response.json()
        assert len(sessions) == 2
        saved_by_id = {s["id"]: s["text"] for s in sessions}
        for sid in session_ids:
            assert saved_by_id[sid] == expected_full_texts[sid], (
                f"session_id={sid} の保存内容が、そのセッション自身のrecognized結果と"
                "一致しない (他セッションの内容が混入している可能性)"
            )
        # AとBの認識結果が異なる発話内容であれば、この時点でsaved_by_idの2値が
        # 一致していないことも取り違え検出の追加の裏付けになる
        assert len(set(saved_by_id.values())) == 2, (
            "AとBの保存内容が同一になっている(取り違えの兆候)"
        )
