from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DynamicSettings(BaseModel):
    """プロセス再起動なしに変更できる設定値。

    `Settings` (起動時に環境変数から1回だけ構築) と異なり、実行中に
    `SettingsRepositoryPort.update()` で差し替えられる。各値は
    「次回利用時」(セッション開始時/校正実行時/SSE接続時/shutdown時) に
    読まれるため、このモデル自体は不変で扱う。
    """

    model_config = ConfigDict(frozen=True)

    max_session_duration_sec: int = Field(default=600, gt=0)
    silence_timeout_sec: int = Field(default=120, gt=0)
    segment_silence_sec: float = Field(default=3.0, gt=0)

    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    mai_locale: str = "ja"
    mai_model_name: str = "mai-transcribe-1"
    mai_timeout_sec: int = Field(default=60, gt=0)

    proofread_timeout_sec: int = Field(default=15, gt=0)
    shutdown_delay_sec: float = Field(default=0.5, gt=0)
    sse_keepalive_sec: int = Field(default=15, gt=0)

    herdr_slot_count: int = Field(default=4, gt=0)

    intent_translation_enabled: bool = False
    screenshot_monitor_index: int = Field(default=1, ge=0)
    intent_translation_timeout_sec: int = Field(default=20, gt=0)

    @model_validator(mode="after")
    def _validate_silence_thresholds(self) -> DynamicSettings:
        """無音区切りはセッション無音タイムアウトより短くなければならない。

        逆転すると、セグメントが1度も切り出されないままセッションが
        タイムアウトで終了する (逐次文字起こしが機能しない)。
        """
        if self.segment_silence_sec >= self.silence_timeout_sec:
            msg = (
                "segment_silence_sec は silence_timeout_sec より小さい必要があります: "
                f"segment_silence_sec={self.segment_silence_sec}, "
                f"silence_timeout_sec={self.silence_timeout_sec}"
            )
            raise ValueError(msg)
        return self
