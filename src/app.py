from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.audio import create_audio_capture
from src.config import (
    GEMINI_MODEL,
    PROOFREAD_PROMPT,
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    VERTEX_SA_INFO,
    validate_api_keys,
)
from src.logging_config import configure_logging
from src.proofreader import Proofreader
from src.routes import router
from src.session_manager import SessionManager
from src.shutdown import ProcessShutdowner
from src.state import AppState

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from contextlib import AbstractAsyncContextManager

    from src.audio_base import AudioCapture

logger = logging.getLogger(__name__)


def _build_lifespan(
    audio_capture: AudioCapture,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        configure_logging()

        for warning in validate_api_keys():
            logger.warning(warning)

        app_state = AppState()
        app.state.app_state = app_state
        app.state.templates_dir = Path(__file__).parent / "templates"
        app.state.session_manager = SessionManager(app_state, audio_capture)
        app.state.shutdowner = ProcessShutdowner()
        if VERTEX_SA_INFO:
            app.state.proofreader = Proofreader(
                sa_info=VERTEX_SA_INFO,
                project=VERTEX_PROJECT,
                location=VERTEX_LOCATION,
                model=GEMINI_MODEL,
                prompt=PROOFREAD_PROMPT,
            )
        else:
            app.state.proofreader = None

        logger.info("Fraetor starting")
        yield
        session_manager: SessionManager = app.state.session_manager
        if app_state.recording:
            await session_manager.stop_session()
        logger.info("Fraetor shutting down")

    return lifespan


def create_app(audio_capture: AudioCapture | None = None) -> FastAPI:
    """FastAPI アプリを組み立てる (コンポジションルート)。

    `audio_capture` を省略すると `create_audio_capture()` がプラットフォーム
    (macOS: 常駐ストリーム / Linux: セッション開閉。design.md 参照) に応じて
    選んだ本番用実装を使う。E2E テスト用の別実装 (`FileAudioCapture` 等) を
    使いたい呼び出し元は、別のコンポジションルートからこの引数で注入する。
    """
    app = FastAPI(lifespan=_build_lifespan(audio_capture or create_audio_capture()))
    app.include_router(router)
    return app


app = create_app()
