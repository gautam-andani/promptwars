"""CultureCompass — FastAPI application entry point.

Run locally with:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import settings, validate_settings
from models.schemas import TravelRequest, TravelResponse
from services import orchestrator
from services.llm_base import UpstreamError

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate configuration and provider setup before serving traffic."""
    validate_settings()
    await orchestrator.startup_checks()
    logger.info("CultureCompass is ready")
    yield


app = FastAPI(
    title="CultureCompass",
    description="GenAI travel & culture discovery platform",
    version="1.0.0",
    lifespan=lifespan,
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_allowed_origins = [
    origin.strip() for origin in settings.ALLOWED_ORIGINS.split(",") if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins or ["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """Serve the single-page frontend."""
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.post("/api/discover", response_model=TravelResponse)
@limiter.limit("5/minute")
async def discover(request: Request, payload: TravelRequest) -> TravelResponse:
    """Run the multi-LLM discovery pipeline for a destination and month.

    Errors are mapped to generic messages; real causes are logged server-side
    and never exposed to clients.
    """
    try:
        return await orchestrator.discover(payload)
    except UpstreamError:
        logger.exception(
            "Upstream AI service failure (destination=%r)", payload.destination
        )
        raise HTTPException(status_code=502, detail="Upstream AI service unavailable")
    except HTTPException:
        raise
    except Exception:
        logger.exception("Unhandled error (destination=%r)", payload.destination)
        raise HTTPException(status_code=500, detail="Something went wrong")
