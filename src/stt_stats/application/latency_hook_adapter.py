from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dictation.domain.ports import SttLatencyHookPort

from src.stt_stats.domain.models import SttLatencySample

if TYPE_CHECKING:
    from src.stt_stats.domain.ports import SttLatencyRepositoryPort

logger = logging.getLogger(__name__)


class SttLatencyRecorder(SttLatencyHookPort):
    """ライブラリからの応答時間の通知を、記録としてリポジトリへ保存する。"""

    def __init__(self, repository: SttLatencyRepositoryPort) -> None:
        self._repository = repository

    def on_stt_completed(
        self,
        *,
        engine: str,
        phase: str,
        duration_sec: float,
        audio_duration_sec: float,
        succeeded: bool,
    ) -> None:
        self._repository.save(
            SttLatencySample(
                recorded_at=datetime.now(UTC),
                engine=engine,
                phase=phase,
                duration_sec=duration_sec,
                audio_duration_sec=audio_duration_sec,
                succeeded=succeeded,
            )
        )
