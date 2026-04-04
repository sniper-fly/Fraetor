from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.routes import router
from src.state import AppState

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    app_state = AppState()
    app.state.app_state = app_state
    app.state.templates_dir = Path(__file__).parent / "templates"
    logger.info("Fraetor starting")
    yield
    logger.info("Fraetor shutting down")


app = FastAPI(lifespan=lifespan)
app.include_router(router)
