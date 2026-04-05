from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.config import validate_api_keys
from src.logging_config import configure_logging
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

    logger.info("Fraetor starting")
    yield
    logger.info("Fraetor shutting down")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
