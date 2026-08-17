import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
import structlog

from .adapters import DEFINITIONS
from .adapters.base import build_search_url
from .adapters.browser import ChallengeNotClearedError, SessionBusyError, assisted_sessions, browser_pool
from .config import settings
from .db import init_db
from .schemas import RetailerInfo, RetailerSessionComplete, RetailerSessionStart, SearchRequest, SearchResult
from .search import SearchNotFound, manager


structlog.configure(processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()])


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        yield
    finally:
        await browser_pool.stop()


app = FastAPI(title="Indian Sneaker Price Finder", version="0.1.0", lifespan=lifespan)


@app.exception_handler(OperationalError)
async def database_unavailable(_request: Request, _exc: OperationalError) -> JSONResponse:
    """Keep infrastructure failures machine-readable without exposing DB details."""
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Search storage is temporarily unavailable. Restart the app and try again."},
    )


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ready", "version": app.version}


@app.get("/api/retailers", response_model=list[RetailerInfo])
async def retailers() -> list[RetailerInfo]:
    from .adapters.base import shared_client
    import datetime as dt
    import time
    import httpx
    
    shared_client._load_persisted_states()
    result = []
    for item in DEFINITIONS:
        host = httpx.URL(item.search_url.split("{")[0]).host or ""
        state = shared_client.state_for(host) if host and item.collection_mode == "automatic" else None
        now = time.monotonic()
        paused = bool(state and state.cooldown_until > now)
        retry_at = None
        if paused and state:
            cooldown_remaining = state.cooldown_until - now
            retry_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=cooldown_remaining)
        result.append(RetailerInfo(
            id=item.id, name=item.name, kind=item.kind, enabled=item.enabled,
            collection_mode="automatic",
            source=item.search_url.replace("{query}", ""),
            health=manager.health[item.id][0], last_error=manager.health[item.id][1],
            paused=paused, retry_at=retry_at,
            session_capable=item.session_capable,
            session_state=assisted_sessions.state_for(item.id),
        ))
    return result


@app.post("/api/search", status_code=status.HTTP_202_ACCEPTED)
async def create_search(body: SearchRequest) -> dict:
    try:
        result = await manager.create(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": str(result.id), "cached": result.cached}


@app.get("/api/search/{search_id}", response_model=SearchResult)
async def get_search(search_id: str) -> SearchResult:
    try:
        return manager.get(search_id)
    except (SearchNotFound, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc


@app.post("/api/search/{search_id}/refresh", status_code=status.HTTP_202_ACCEPTED)
async def refresh_search(search_id: str) -> dict:
    try:
        previous = manager.get(search_id)
    except (SearchNotFound, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc
    result = await manager.create(previous.request.model_copy(deep=True), bypass_cache=True)
    return {"id": str(result.id), "cached": False}


def _definition(retailer_id: str):
    return next((item for item in DEFINITIONS if item.id == retailer_id), None)


@app.post("/api/retailers/{retailer_id}/session/start")
async def start_retailer_session(retailer_id: str, body: RetailerSessionStart) -> dict:
    definition = _definition(retailer_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Retailer not found")
    if not definition.session_capable:
        raise HTTPException(status_code=409, detail="This retailer does not support assisted sessions")
    try:
        result = manager.get(str(body.search_id))
    except SearchNotFound as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc
    try:
        session = await assisted_sessions.start(
            retailer_id, str(body.search_id), build_search_url(
                definition.search_url,
                result.request,
                include_brand=definition.kind in {"boutique", "marketplace"},
            )
        )
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Assisted browser is unavailable") from exc
    return session


@app.post("/api/retailers/{retailer_id}/session/complete", status_code=status.HTTP_202_ACCEPTED)
async def complete_retailer_session(retailer_id: str, body: RetailerSessionComplete) -> dict:
    definition = _definition(retailer_id)
    if not definition:
        raise HTTPException(status_code=404, detail="Retailer not found")
    try:
        previous = manager.get(str(body.search_id))
    except SearchNotFound as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc
    try:
        await assisted_sessions.complete(retailer_id, str(body.search_id), challenge_cleared=body.challenge_cleared)
    except ChallengeNotClearedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        refreshed = await manager.create(previous.request.model_copy(deep=True), bypass_cache=True)
    except SearchNotFound as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc
    return {"id": str(refreshed.id), "cached": False}


@app.delete("/api/retailers/{retailer_id}/session")
async def clear_retailer_session(retailer_id: str) -> dict:
    if not _definition(retailer_id):
        raise HTTPException(status_code=404, detail="Retailer not found")
    await assisted_sessions.reset(retailer_id)
    return {"retailer_id": retailer_id, "session_state": "none"}


@app.get("/api/search/{search_id}/events")
async def search_events(search_id: str, request: Request) -> StreamingResponse:
    try:
        manager.get(search_id)
    except (SearchNotFound, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Search not found") from exc

    async def stream():
        async for item in manager.events(search_id):
            if await request.is_disconnected():
                break
            yield f"event: {item['event']}\ndata: {json.dumps(item['data'], default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if settings.frontend_build.is_dir():
    assets = settings.frontend_build / "_app"
    if assets.is_dir():
        app.mount("/_app", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str):
        candidate = (settings.frontend_build / path).resolve()
        build_root = settings.frontend_build.resolve()
        if candidate.is_relative_to(build_root) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(build_root / "index.html")
