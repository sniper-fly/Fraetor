"""プラットフォーム分岐 (Linux実機) のE2Eテスト。

`PerSessionStreamCapture` がセッションごとにストリームを開閉する
実装であることを design.md で確認済み。ここでは録音開始/停止を
複数回連続してもプロセスがクラッシュしないことを実マイクデバイスで
検証する (この検証だけは `FileAudioCapture` ではなく実デバイスの
ストリーム開閉ライフサイクル自体を対象にするため `fraetor_server` を使う)。
"""

from __future__ import annotations

import asyncio

import httpx

_TOGGLE_INTERVAL_SEC = 0.5
_TOGGLE_CYCLES = 3


class TestRepeatedStreamOpenClose:
    async def test_repeated_start_stop_does_not_crash_process(
        self, fraetor_server: str
    ) -> None:
        """正常系: 録音開始→停止を複数回連続し、ストリーム開閉でクラッシュしない"""
        async with httpx.AsyncClient(base_url=fraetor_server) as client:
            for _ in range(_TOGGLE_CYCLES):
                start_response = await client.post("/api/toggle-recording")
                assert start_response.status_code == 200
                await asyncio.sleep(_TOGGLE_INTERVAL_SEC)

                stop_response = await client.post("/api/toggle-recording")
                assert stop_response.status_code == 200
                await asyncio.sleep(_TOGGLE_INTERVAL_SEC)

            # プロセスが生きていること (index への疎通) を最終確認
            health_response = await client.get("/")
            assert health_response.status_code == 200
