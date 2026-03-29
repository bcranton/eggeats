import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.api import admin as admin_router
from app.api import auth as auth_router
from app.api import map as map_router
from app.api.auth import get_admin_session
from app.database import get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rate limiter — keyed by client IP
limiter = Limiter(key_func=get_remote_address)

# In Docker (Railway), frontend is copied to /frontend.
# In local dev with docker-compose, it's mounted at /frontend too.
# For local non-Docker runs, fall back to relative path from repo root.
_docker_static = Path("/frontend")
_repo_static = Path(__file__).parent.parent.parent / "frontend"
STATIC_DIR = _docker_static if _docker_static.exists() else _repo_static


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.config import get_settings
    settings = get_settings()
    if settings.environment == "production":
        missing = settings.validate_for_production()
        if missing:
            raise RuntimeError(
                f"Missing required environment variables for production: {', '.join(missing)}"
            )
    logger.info("Starting Egg Eats API (environment=%s)", settings.environment)
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Egg Eats",
    description="API for Egg Eats — A Northernlion Travel Guide",
    version="1.0.0",
    lifespan=lifespan,
    # API docs disabled — endpoints are admin-only or internal
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

from app.config import get_settings as _get_settings
_settings = _get_settings()
_allowed_origins = (
    ["https://eggeats.com", "https://www.eggeats.com"]
    if _settings.environment == "production"
    else ["http://localhost:8000", "http://localhost:3000", "http://127.0.0.1:8000"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Cookie", "Authorization"],
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
    def serve_admin(
        admin_token: str | None = Cookie(default=None),
        db: Session = Depends(get_db),
    ):
        # Server-side auth check — redirect to Google login if not authenticated.
        # The JS also does a session check, but this prevents unauthenticated
        # users from even reading the page source.
        try:
            get_admin_session(admin_token=admin_token, db=db)
        except HTTPException:
            return RedirectResponse(url="/auth/google", status_code=302)
        return FileResponse(
            STATIC_DIR / "admin.html",
            # Never cache admin page — auth state must always be re-checked
            headers={"Cache-Control": "no-store"},
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

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    if STATIC_DIR.exists():
        return FileResponse(STATIC_DIR / "404.html", status_code=404)
    return Response(content="404 Not Found", status_code=404)
