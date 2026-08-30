"""
FastAPI application — entry point for the BI SQL Assistant API.

The API is the only component that holds credentials: the React client is a pure
consumer of these endpoints and never sees a database URL or a Groq API key.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import initialize_schema, router
from app.config import settings
from app.database.seed import seed_database
from app.llm.client import close_llm_provider, get_llm_provider
from app.monitoring.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown hooks."""
    # ── Startup ───────────────────────────────────────────────
    setup_logging(debug=settings.debug)
    logger.info("🚀 Starting BI SQL Assistant API...")

    if not settings.llm_configured:
        logger.warning(
            "⚠️  GROQ_API_KEY is not set. The API will start, but /api/query "
            "will return 503 until a key is configured in the environment."
        )
    else:
        # Instantiate eagerly so a misconfiguration surfaces in the startup log.
        get_llm_provider()

    try:
        seed_database()
    except Exception as e:
        logger.warning(f"Database seeding skipped: {e}")

    try:
        initialize_schema()
    except Exception as e:
        logger.error(f"Schema initialization failed: {e}")

    logger.info(f"✅ API ready at http://{settings.app_host}:{settings.app_port}")
    yield

    # ── Shutdown ──────────────────────────────────────────────
    await close_llm_provider()
    logger.info("👋 Shutting down BI SQL Assistant API...")


# ── App Instance ──────────────────────────────────────────────
app = FastAPI(
    title="LLM-Powered BI SQL Assistant",
    description=(
        "An AI-powered natural language interface for querying business data. "
        "Convert plain English questions into validated SQL queries, "
        "auto-generate visualizations, and receive executive-level insights. "
        "Inference runs on Groq-hosted openai/gpt-oss-20b; the model's internal "
        "reasoning is suppressed and never returned by any endpoint."
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS Middleware ───────────────────────────────────────────
# Explicit origins only: the API answers a browser client, so a wildcard would
# let any site on the internet drive it with the user's session.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ── Uniform error envelope ────────────────────────────────────

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Normalise every HTTP error into {error, message, ...}."""
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        payload = detail
    else:
        payload = {"error": "http_error", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Return a readable message for malformed request bodies."""
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(part) for part in first.get("loc", []) if part != "body")
    message = first.get("msg", "Invalid request.")
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "message": f"{field}: {message}" if field else message,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak a stack trace or an internal message to the client."""
    logger.exception(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "An unexpected server error occurred.",
        },
    )


# ── Register Routes ──────────────────────────────────────────
app.include_router(router)


# ── Root Endpoint ─────────────────────────────────────────────
@app.get("/", tags=["Meta"])
async def root():
    return {
        "name": "LLM-Powered BI SQL Assistant",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )
