"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse

from .config import Settings, get_settings
from .store import SaveStore


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
            "JUNIMO_SAVES_DIR and exposes structured data with caching."
        ),
        version="0.1.0",
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
    async def get_save(slot: str, store: SaveStore = Depends(get_store)) -> JSONResponse:
        try:
            entry = await store.get(slot, force_refresh=False)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"parse failed: {exc}") from exc
        return JSONResponse(_serialize_entry(entry))

    @app.post("/saves/{slot}/refresh", dependencies=[Depends(require_token)])
    async def refresh_save(slot: str, store: SaveStore = Depends(get_store)) -> JSONResponse:
        try:
            entry = await store.get(slot, force_refresh=True)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"parse failed: {exc}") from exc
        return JSONResponse(_serialize_entry(entry))

    @app.post("/refresh", dependencies=[Depends(require_token)])
    async def refresh_all(store: SaveStore = Depends(get_store)) -> dict:
        results = await store.refresh_all()
        return {"results": results}

    return app


def _serialize_entry(entry) -> dict:
    return {
        "slot": entry.slot,
        "source_path": entry.source_path,
        "source_mtime": entry.source_mtime,
        "source_size": entry.source_size,
        "parsed_at": entry.parsed_at,
        "parse_duration_ms": entry.parse_duration_ms,
        "data": entry.data,
    }


app = create_app()
