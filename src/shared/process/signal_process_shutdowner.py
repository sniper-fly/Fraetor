from __future__ import annotations

import asyncio
import os
import signal

from src.shared.process.ports import ProcessShutdownerPort


class ProcessShutdowner(ProcessShutdownerPort):
    """プロセス終了をスケジュールする。

    テストでは実プロセスへの signal 送出を避けるため、この具象クラス自体を
    DI で注入し、フェイクに置き換える。
    """

    def schedule(self, delay_sec: float) -> None:
        loop = asyncio.get_running_loop()
        loop.call_later(delay_sec, os.kill, os.getpid(), signal.SIGTERM)
