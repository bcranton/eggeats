import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response

from app.api import map as map_router
from app.api import auth as auth_router
from app.api import admin as admin_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import os

# In Docker (Railway), frontend is copied to /frontend.
# In local dev with docker-compose, it's mounted at /frontend too.
# For local non-Docker runs, fall back to relative path from repo root.
_docker_static = Path("/frontend")
_repo_static = Path(__file__).parent.parent.parent / "frontend"
STATIC_DIR = _docker_static if _docker_static.exists() else _repo_static


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Egg Eats API")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Egg Eats",
    description="API for Egg Eats — A Northernlion Travel Guide",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(map_router.router)
app.include_router(auth_router.router)
app.include_router(admin_router.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}


# Serve frontend static files
if STATIC_DIR.exists():
    # HTML pages: cache for 5 minutes in browsers.
    # This is the key lever for Mapbox cost — a returning visitor whose browser
    # has the page cached will NOT trigger a new mapboxgl.Map() init, so it
    # doesn't count against the 50k free monthly map loads.
    # JS/CSS assets get a longer cache (1 hour) since they're content-addressed.
    HTML_CACHE = "public, max-age=300, stale-while-revalidate=60"   # 5 min
    ASSET_CACHE = "public, max-age=3600, stale-while-revalidate=300" # 1 hour

    @app.get("/admin.html")
    def serve_admin():
        return FileResponse(
            STATIC_DIR / "admin.html",
            headers={"Cache-Control": HTML_CACHE},
        )

    @app.get("/")
    def serve_index():
        return FileResponse(
            STATIC_DIR / "index.html",
            headers={"Cache-Control": HTML_CACHE},
        )

    @app.middleware("http")
    async def add_asset_cache_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/js/", "/css/")):
            response.headers["Cache-Control"] = ASSET_CACHE
        return response

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
