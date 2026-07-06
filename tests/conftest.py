from __future__ import annotations

import pytest

from backend.config import get_settings
from backend.db import init_db


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "trading-test.duckdb"))
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    init_db(get_settings())
    yield
    get_settings.cache_clear()

