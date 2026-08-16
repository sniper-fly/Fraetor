from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.containers import Container
from src.logging_config import configure_logging
from src.presentation.routes import (
    herdr_routes,
    history_routes,
    page_routes,
    proofread_routes,
    recording_routes,
    settings_routes,
    shutdown_routes,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from contextlib import AbstractAsyncContextManager

    from src.dictation.domain.ports import AudioCapturePort

logger = logging.getLogger(__name__)


def _validate_secrets(container: Container) -> list[str]:
    secrets = container.secrets()
    warnings: list[str] = []
    if not secrets.mai_api_key:
        warnings.append("MAI_API_KEY が未設定です。音声認識は利用できません。")
    if not secrets.vertex_sa_info:
        warnings.append("VERTEX_SA_INFO が未設定です。テキスト校正は利用できません。")
    return warnings


def _build_lifespan(
    container: Container,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        configure_logging()

        for warning in _validate_secrets(container):
            logger.warning(warning)

        settings_repository = container.settings_repository()
        app.state.app_state = container.app_state()
        app.state.templates_dir = container.templates_dir()
        app.state.recording_session_service = container.recording_session_service()
        app.state.transcription_queue = container.transcription_queue()
        app.state.shutdowner = container.shutdowner()
        app.state.history_repository = container.history_repository()
        app.state.finalize_session_use_case = container.finalize_session_use_case()
        app.state.proofread_text_use_case = container.proofread_text_use_case()
        app.state.settings_repository = settings_repository
        app.state.herdr_client = container.herdr_client()

        app.state.transcription_queue.start()
        logger.info("Fraetor starting")
        yield
        app_state = app.state.app_state
        if app_state.recording:
            await app.state.recording_session_service.stop_session()
        await app.state.transcription_queue.shutdown(
            timeout=settings_repository.get().mai_timeout_sec + 5
        )
        logger.info("Fraetor shutting down")

    return lifespan


def create_app(audio_capture: AudioCapturePort | None = None) -> FastAPI:
    """FastAPI アプリを組み立てる (コンポジションルート)。

    `audio_capture` を省略すると Container が組み立てたプラットフォーム別の
    本番用実装を使う。E2E テスト用の別実装 (`FileAudioCapture` 等) を
    使いたい呼び出し元は、この引数で Container のデフォルトを上書きする。
    """
    container = Container()
    if audio_capture is not None:
        container.audio_capture.override(audio_capture)

    app = FastAPI(lifespan=_build_lifespan(container))
    app.include_router(page_routes.router)
    app.include_router(recording_routes.router)
    app.include_router(history_routes.router)
    app.include_router(proofread_routes.router)
    app.include_router(shutdown_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(herdr_routes.router)
    return app


app = create_app()
