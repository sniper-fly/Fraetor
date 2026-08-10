from __future__ import annotations

from typing import TYPE_CHECKING

from src.dictation.infrastructure.vad.silero_vad_detector import (
    SileroSpeechActivityDetector,
)

if TYPE_CHECKING:
    from src.dictation.domain.ports import SpeechActivityDetectorPort
    from src.shared.config.ports import SettingsRepositoryPort


def create_vad(
    *, settings_repository: SettingsRepositoryPort, sample_rate: int
) -> SpeechActivityDetectorPort:
    """VAD を生成する。閾値は生成時 (= セッション開始時) に読む。

    `vad_threshold` を DI 配線時ではなく呼び出し時に解決することで、
    設定画面からの変更が次のセッションから反映される。VAD インスタンス
    自体はセッションごとに作り直されるため、生存中の差し替えは不要。
    """
    settings = settings_repository.get()
    return SileroSpeechActivityDetector(
        sample_rate=sample_rate, threshold=settings.vad_threshold
    )
