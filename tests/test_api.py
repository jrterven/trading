from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

import backend.main as backend_main


def test_api_returns_no_bars_without_alpaca_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "api-test.duckdb"))
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "")
    import backend.config as config

    config.get_settings.cache_clear()
    app_module = importlib.reload(backend_main)

    with TestClient(app_module.app) as client:
        response = client.get(
            "/api/bars",
            params={
                "symbol": "AAPL",
                "timeframe": "1Day",
                "start": "2026-01-01",
                "end": "2026-02-01",
            },
        )

    assert response.status_code == 200
    assert response.json() == []


def test_strategy_environment_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "api-env-test.duckdb"))
    import backend.config as config

    config.get_settings.cache_clear()
    app_module = importlib.reload(backend_main)

    with TestClient(app_module.app) as client:
        response = client.get("/api/strategy/environment")

    assert response.status_code == 200
    payload = response.json()
    assert payload["python_executable"]
    assert payload["python_version"]
    assert payload["strategy_timeout_seconds"] >= 1
    assert "pandas" in payload["packages"]
    assert "torch" in payload["packages"]
