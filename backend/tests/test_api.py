import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from types import SimpleNamespace
from uuid import uuid4

from app.assisted_runtime import AssistedBrowserUnavailableError
from app.db import init_db
from app.main import app, database_unavailable, health, retailers, start_retailer_session
from app.schemas import RetailerSessionStart, SearchRequest


async def test_health_validation_and_contract():
    init_db()
    assert (await health())["status"] == "ready"
    configured = await retailers()
    assert len(configured) == 15
    assert {item.id for item in configured} >= {"nike", "nykaa_fashion", "myntra"}
    assert sum(item.collection_mode == "automatic" for item in configured) == 15
    assert all(item.source.startswith("https://") for item in configured)
    with pytest.raises(ValidationError):
        SearchRequest(query="x", uk_size="huge")
    paths = app.openapi()["paths"]
    assert set(paths) >= {
        "/api/health", "/api/retailers", "/api/search",
        "/api/search/{search_id}", "/api/search/{search_id}/events",
        "/api/search/{search_id}/refresh",
    }
    assert any(route.path == "/{path:path}" for route in app.routes)


async def test_database_failures_are_returned_as_structured_service_errors():
    response = await database_unavailable(None, OperationalError("insert", {}, Exception("readonly")))
    assert response.status_code == 503
    assert response.media_type == "application/json"
    assert b'"detail"' in response.body
    assert b"readonly" not in response.body


async def test_assisted_session_endpoint_checks_runtime_and_returns_viewer(monkeypatch):
    from app import main as main_module

    search_id = uuid4()
    monkeypatch.setattr(
        main_module.manager, "get",
        lambda _search_id: SimpleNamespace(
            request=SearchRequest(query="Club C", uk_size="9"),
            resolved_query="Club C 85",
        ),
    )

    async def start_ok(retailer_id, actual_search_id, url):
        assert retailer_id == "reebok" and actual_search_id == str(search_id)
        assert "club+c+85" in url
        return {"viewer_url": "http://127.0.0.1:6080/vnc.html"}

    monkeypatch.setattr(main_module.assisted_sessions, "start", start_ok)
    result = await start_retailer_session("reebok", RetailerSessionStart(search_id=search_id))
    assert result["viewer_url"].endswith("vnc.html")

    async def start_unavailable(*_args, **_kwargs):
        raise AssistedBrowserUnavailableError("x_display")

    monkeypatch.setattr(main_module.assisted_sessions, "start", start_unavailable)
    with pytest.raises(HTTPException) as caught:
        await start_retailer_session("reebok", RetailerSessionStart(search_id=search_id))
    assert caught.value.status_code == 503
    assert "Restart the app" in caught.value.detail
