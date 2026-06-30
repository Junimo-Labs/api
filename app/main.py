"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .store import SaveCacheEntry, SaveStore


def _create_store(settings: Settings) -> SaveStore:
    return SaveStore(settings=settings)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.store = _create_store(settings)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Junimo-Api",
        description=(
            "Stardew Valley save parser service. Parses XML saves under "
            "JUNIMO_SAVES_DIR and exposes structured data with caching. "
            "See docs/PROTOCOL.md for the data contract."
        ),
        version="0.2.0",
        lifespan=_lifespan,
    )

    def get_store() -> SaveStore:
        return app.state.store

    def require_token(
        authorization: Optional[str] = Header(default=None),
    ) -> None:
        token = app.state.settings.api_token
        if not token:
            return
        expected = f"Bearer {token}"
        if authorization != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing bearer token",
            )

    async def _load(slot: str, force_refresh: bool) -> SaveCacheEntry:
        store: SaveStore = app.state.store
        try:
            return await store.get(slot, force_refresh=force_refresh)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"parse failed: {exc}") from exc

    @app.get("/healthz")
    def healthz() -> dict:
        settings: Settings = app.state.settings
        return {
            "status": "ok",
            "saves_dir": str(settings.saves_dir),
            "saves_dir_exists": settings.saves_dir.exists(),
        }

    @app.get("/saves")
    def list_saves(store: SaveStore = Depends(get_store)) -> dict:
        return {"slots": store.list_slots()}

    @app.get("/saves/{slot}")
    async def get_save(slot: str) -> JSONResponse:
        entry = await _load(slot, force_refresh=False)
        return JSONResponse(_serialize_entry(entry, view="summary"))

    @app.get("/saves/{slot}/farm")
    async def get_save_farm(slot: str) -> JSONResponse:
        entry = await _load(slot, force_refresh=False)
        return JSONResponse(_serialize_entry(entry, view="farm"))

    @app.get("/saves/{slot}/full")
    async def get_save_full(slot: str) -> JSONResponse:
        entry = await _load(slot, force_refresh=False)
        return JSONResponse(_serialize_entry(entry, view="full"))

    @app.post("/saves/{slot}/refresh", dependencies=[Depends(require_token)])
    async def refresh_save(slot: str) -> JSONResponse:
        entry = await _load(slot, force_refresh=True)
        return JSONResponse(_serialize_entry(entry, view="summary"))

    @app.post("/refresh", dependencies=[Depends(require_token)])
    async def refresh_all(store: SaveStore = Depends(get_store)) -> dict:
        results = await store.refresh_all()
        return {"results": results}

    return app


def _serialize_entry(entry: SaveCacheEntry, *, view: str) -> dict:
    """Project a cache entry to one of the three documented views.

    `view` ∈ {"summary", "farm", "full"} mirrors PROTOCOL.md §2.3/§2.4/§2.6.
    """
    base = {
        "slot": entry.slot,
        "source_path": entry.source_path,
        "source_mtime": entry.source_mtime,
        "source_size": entry.source_size,
        "parsed_at": entry.parsed_at,
        "parse_duration_ms": entry.parse_duration_ms,
    }
    if view == "summary":
        base["data"] = entry.data.get("summary")
    elif view == "farm":
        base["data"] = entry.data.get("farm")
    else:
        base["data"] = {
            "summary": entry.data.get("summary"),
            "farm": entry.data.get("farm"),
        }
    return base


app = create_app()
