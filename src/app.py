from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

from src.hotkey import HotkeyListener
from src.routes import router
from src.state import AppState, run_hotkey_handler

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

    hotkey_listener = HotkeyListener(app_state.hotkey_queue)
    listener_task = asyncio.create_task(hotkey_listener.run())
    handler_task = asyncio.create_task(run_hotkey_handler(app_state))

    logger.info("Fraetor starting")
    yield
    logger.info("Fraetor shutting down")

    handler_task.cancel()
    hotkey_listener.stop()
    listener_task.cancel()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
