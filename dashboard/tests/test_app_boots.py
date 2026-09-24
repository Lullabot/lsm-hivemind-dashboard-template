"""Boot-time smoke tests: every page loads against the example seed data."""

import pytest
from starlette.testclient import TestClient


@pytest.fixture()
def client():
    import app
    return TestClient(app.app)


@pytest.mark.parametrize("path", [
    "/",
    "/briefing",
    "/people",
    "/retrospector",
    "/automations",
    "/api/data",
    "/api",
    "/project/ProjectAlpha",
    "/memory-map",
    "/api/memory-map",
])
def test_page_loads(client, path):
    response = client.get(path)
    assert response.status_code == 200, f"{path} returned {response.status_code}"


def test_health_returns_json(client):
    response = client.get("/health")
    # 503 is acceptable on a fresh checkout — some data sources are stale.
    assert response.status_code in (200, 503)
    assert response.headers["content-type"].startswith("application/json")


def test_memory_map_hint_shows_only_for_example_store(client, monkeypatch):
    import app
    monkeypatch.setattr(app, "kenkeep_sources", lambda: [{"example": True}])
    assert 'data-hint-id="memory-map-example"' in client.get("/memory-map").text
    monkeypatch.setattr(app, "kenkeep_sources", lambda: [{"layer": "L1"}])
    assert 'data-hint-id="memory-map-example"' not in client.get("/memory-map").text
