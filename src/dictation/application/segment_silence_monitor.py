from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class SegmentSilenceMonitor:
    """発話が止まってから一定時間経過したタイミングでコールバックを呼ぶ。

    `SessionTimeoutMonitor` と同じ「正確な残り時間だけ寝て起きる」方式だが、
    1セッション中に何度も発火するため発火後もループを続ける点が異なる。

    無音が続く間は `segment_silence_sec` おきにコールバックが呼ばれ続ける
    (意図的)。「送るものがあるか」の判定は送信済み位置を知っている
    STT クライアント側の no-op ガードに委ねる。ここで抑制しようとすると
    監視側が STT の内部状態を二重に持つことになる。
    """

    def __init__(
        self,
        *,
        segment_silence_sec: float,
        last_speech_time_fn: Callable[[], float],
        on_silence: Callable[[], Awaitable[None]],
    ) -> None:
        self._segment_silence_sec = segment_silence_sec
        self._last_speech_time_fn = last_speech_time_fn
        self._on_silence = on_silence
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._task and self._task is not asyncio.current_task():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _watch(self) -> None:
        while True:
            last_speech = self._last_speech_time_fn()
            remaining = last_speech + self._segment_silence_sec - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
                continue
            await self._on_silence()
            # 発火直後に「新たに正当な無音区切り」が起こりうる最速は
            # 「発話が始まって終わるまで (>0) + segment_silence_sec」後なので、
            # この区間は何もチェックせずに寝てよい。目覚めた時点で残り時間の
            # 再計算に戻るため、区切りタイミングはずれない。
            await asyncio.sleep(self._segment_silence_sec)
