"""FastAPI application entry point for the Sentiment-Routed Feedback API."""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import init_db

# Load environment variables from backend/.env (if present) before anything
# reads them. This is where GEMINI_API_KEY / GEMINI_MODEL_NAME should live for
# local development. The file is gitignored and must never be committed.
# python-dotenv is optional: if it isn't installed we fall back to whatever is
# already set in the real environment.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
try:
    from dotenv import load_dotenv

    # override=True makes backend/.env authoritative: the values in the file
    # win over any stale GEMINI_API_KEY / GEMINI_MODEL_* already exported in the
    # shell that launched the server. The .env only defines GEMINI_* here, so
    # this does not clobber test-managed vars like SUBMISSIONS_DB_PATH.
    load_dotenv(_BACKEND_DIR / ".env", override=True)
except ModuleNotFoundError:
    pass

logger = logging.getLogger(__name__)


def _log_nlp_readiness() -> None:
    """Log whether NLP enrichment is fully configured, without leaking the key."""
    has_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    try:
        # Importing the enrichment service adds the repo root to sys.path so the
        # nlp_processing package becomes importable from the backend/ cwd.
        from app.services import enrichment  # noqa: F401
        import importlib.util

        pkg_available = importlib.util.find_spec("nlp_processing") is not None
    except Exception:
        pkg_available = False

    if has_key and pkg_available:
        logger.info("NLP enrichment: ENABLED (API key present, package importable)")
    else:
        reasons = []
        if not has_key:
            reasons.append("GEMINI_API_KEY not set")
        if not pkg_available:
            reasons.append("nlp_processing not importable")
        logger.warning(
            "NLP enrichment: DISABLED — %s. Submissions will still work; "
            "enrichment will be marked failed.",
            "; ".join(reasons),
        )


def _bootstrap_admin() -> None:
    """Ensure an admin account exists from environment configuration.

    In production the admin credentials are supplied via ``ADMIN_USERNAME`` and
    ``ADMIN_PASSWORD`` env vars (never hardcoded). When both are present the
    admin user is created/updated on startup. When absent, nothing is seeded so
    local/dev databases keep whatever admin they already have.
    """
    username = os.environ.get("ADMIN_USERNAME", "").strip()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not (username and password):
        logger.info(
            "Admin bootstrap skipped (ADMIN_USERNAME/ADMIN_PASSWORD not set)."
        )
        return
    try:
        from app.services.auth_service import AuthService

        AuthService().create_admin(username, password)
        logger.info("Admin user '%s' ensured from environment.", username)
    except Exception:  # pragma: no cover - never block startup on seeding
        logger.exception("Failed to bootstrap admin user from environment")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize database on startup."""
    init_db()
    _bootstrap_admin()
    _log_nlp_readiness()
    yield


app = FastAPI(
    title="Spectrum Feedback API",
    description="REST API for sentiment-routed customer feedback intake",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration — allow the React dev server plus any production origin
# supplied via FRONTEND_ORIGIN. In the recommended single-service deploy the
# frontend is served same-origin, so CORS is not needed there; this stays for
# split-hosting or local dev.
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra_origin = os.environ.get("FRONTEND_ORIGIN", "").strip()
if _extra_origin:
    origins.append(_extra_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Router includes
from app.routes.auth import router as auth_router
from app.routes.feedback import router as feedback_router
from app.routes.admin import router as admin_router

app.include_router(auth_router, prefix="/api/auth")
app.include_router(feedback_router, prefix="/api")
app.include_router(admin_router, prefix="/api/admin")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Serve the built frontend (single-service production deploy).
#
# When the Vite build output exists at ../frontend/dist, mount it so FastAPI
# serves the SPA on the same origin as the API (no CORS needed). Hashed assets
# are served from /assets; every other non-API path falls back to index.html so
# client-side routes (e.g. /admin/dashboard) resolve. In local dev the dist
# folder is absent, so this block is skipped and Vite serves the frontend.
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = _BACKEND_DIR.parent / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    _assets_dir = _FRONTEND_DIST / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve a static file when it exists, else the SPA entry point.

        Registered after the API routers, so /api/* and /health always win.
        """
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_FRONTEND_DIST / "index.html"))

    logger.info("Serving built frontend from %s", _FRONTEND_DIST)
