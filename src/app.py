from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

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
from src.state import AppState

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()

    for warning in validate_api_keys():
        logger.warning(warning)

    app_state = AppState()
    app.state.app_state = app_state
    app.state.templates_dir = Path(__file__).parent / "templates"
    app.state.session_manager = SessionManager(app_state)
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


app = FastAPI(lifespan=lifespan)
app.include_router(router)
