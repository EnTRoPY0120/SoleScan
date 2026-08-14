import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.db import init_db
from app.main import app, database_unavailable, health, retailers
from app.schemas import SearchRequest


async def test_health_validation_and_contract():
    init_db()
    assert (await health())["status"] == "ready"
    configured = await retailers()
    assert len(configured) == 15
    assert {item.id for item in configured} >= {"nike", "nykaa_fashion", "myntra"}
    assert sum(item.collection_mode == "automatic" for item in configured) == 7
    assert sum(item.collection_mode == "manual" for item in configured) == 8
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
