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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize database on startup."""
    init_db()
    _log_nlp_readiness()
    yield


app = FastAPI(
    title="Spectrum Feedback API",
    description="REST API for sentiment-routed customer feedback intake",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration — allow React dev server and production origins
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Router includes
from app.routes.auth import router as auth_router
from app.routes.submissions import router as submissions_router
from app.routes.admin import router as admin_router

app.include_router(auth_router, prefix="/api/auth")
app.include_router(submissions_router, prefix="/api")
app.include_router(admin_router, prefix="/api/admin")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
