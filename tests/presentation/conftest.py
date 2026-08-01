from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from src.presentation.app import create_app

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def client() -> Generator[TestClient]:
    """テストごとに新規アプリを生成し、Container(AppState等)の状態を分離する。"""
    with TestClient(create_app()) as c:
        yield c
