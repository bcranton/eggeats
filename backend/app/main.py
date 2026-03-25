import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

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
    logger.info("Starting Northernlion Travel Guide API")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Northernlion Travel Guide",
    description="API for the Northernlion Vancouver (and beyond) Travel Guide",
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
    # Serve specific HTML files explicitly before catch-all static mount
    @app.get("/admin.html")
    def serve_admin():
        return FileResponse(STATIC_DIR / "admin.html")

    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="frontend")
