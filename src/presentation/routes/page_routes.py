from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    templates_dir = request.app.state.templates_dir
    html_path = templates_dir / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
