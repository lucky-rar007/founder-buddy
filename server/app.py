"""
Founder Buddy — FastAPI Application.

Main web server entry point. Serves the SPA frontend, handles API routes,
and manages WebSocket connections for real-time progress updates.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Ensure workspace root is on sys.path
_WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(_WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKSPACE_ROOT))

from shared.database import init_db
from server.routes import onboarding, config, ingestion, dashboard, rag

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITER (M-1)
# ─────────────────────────────────────────────────────────────────────

_request_history: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT_WINDOW = 60.0  # seconds
_MAX_REQUESTS_PER_WINDOW = 60  # requests per minute per IP


# ─────────────────────────────────────────────────────────────────────
# APPLICATION LIFESPAN (L-3)
# ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager replacing deprecated on_event hooks."""
    logger.info("[Server] Initializing database...")
    init_db()

    # Initialize dashboard-specific tables
    from dashboard.db import init_db as dashboard_init_db
    dashboard_init_db()

    # Start background scheduler
    from dashboard.scheduler import scheduler
    await scheduler.start()
    logger.info("[Server] Founder Buddy server started.")

    yield

    logger.info("[Server] Stopping background services...")
    await scheduler.stop()


# ─────────────────────────────────────────────────────────────────────
# APPLICATION FACTORY
# ─────────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="Founder Buddy",
        description="Intelligent workspace assistant for founders",
        version="2.0.0",
        lifespan=lifespan,
        # Disable OpenAPI docs in production if desired
        # docs_url=None, redoc_url=None
    )

    # CORS middleware — configurable via ALLOWED_ORIGINS env var for cloud deployments
    import os
    _env_origins = os.environ.get("ALLOWED_ORIGINS", "")
    _allowed_origins = (
        [o.strip() for o in _env_origins.split(",") if o.strip()]
        if _env_origins
        else [
            "http://localhost:8080",
            "http://127.0.0.1:8080",
            "http://localhost:3000",  # Dev server fallback
        ]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
    )

    # ── Security Headers Middleware ──────────────────────────────
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    # Rate Limiting Middleware (M-1)
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client else "127.0.0.1"
            # Exempt local single-user desktop traffic from rate limiting
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                now = time.time()
                timestamps = [t for t in _request_history[client_ip] if now - t < _RATE_LIMIT_WINDOW]
                if len(timestamps) >= _MAX_REQUESTS_PER_WINDOW:
                    return JSONResponse(
                        status_code=429,
                        content={"success": False, "error": "Rate limit exceeded. Please wait a minute before retrying."}
                    )
                timestamps.append(now)
                _request_history[client_ip] = timestamps

        return await call_next(request)

    # ─── API Routes ──────────────────────────────────────────────
    app.include_router(onboarding.router, prefix="/api/onboarding", tags=["Onboarding"])
    app.include_router(config.router, prefix="/api/config", tags=["Config"])
    app.include_router(ingestion.router, prefix="/api/ingestion", tags=["Ingestion"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
    app.include_router(rag.router, prefix="/api/rag", tags=["RAG"])

    # ─── Static Files ────────────────────────────────────────────
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        # Mount CSS/JS subdirectories
        css_dir = static_dir / "css"
        js_dir = static_dir / "js"

        if css_dir.exists():
            app.mount("/css", StaticFiles(directory=str(css_dir)), name="css")
        if js_dir.exists():
            app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")

        # Mount static root for any other assets (images, fonts, etc.)
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/logo.png")
    @app.get("/assets/logo.png")
    async def serve_logo():
        """Serve logo image asset from assets directory."""
        logo_path = static_dir / "assets" / "logo.png"
        if logo_path.exists():
            return FileResponse(str(logo_path))
        return JSONResponse(status_code=404, content={"error": "Logo not found"})

    # ─── SPA Catch-All ───────────────────────────────────────────
    @app.get("/")
    async def serve_index():
        """Serve the SPA index page."""
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse(
            status_code=404,
            content={"error": "Frontend not found. Ensure server/static/index.html exists."}
        )

    @app.get("/health")
    async def health_check():
        """Comprehensive production health check endpoint."""
        db_ok = False
        vector_ok = False
        chunks_count = 0
        scheduler_running = False

        try:
            from shared.database import get_db
            with get_db() as conn:
                conn.execute("SELECT 1")
                db_ok = True
        except Exception as de:
            logging.error(f"[Health] DB check failed: {de}")

        try:
            from rag.vectorstore import ChromaVectorStore
            vs = ChromaVectorStore()
            chunks_count = vs.get_count()
            vector_ok = True
        except Exception as ve:
            logging.warning(f"[Health] Vector store check notice: {ve}")

        try:
            from dashboard.scheduler import scheduler
            scheduler_running = scheduler._started if hasattr(scheduler, "_started") else True
        except Exception:
            pass

        status_code = 200 if db_ok else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if db_ok else "degraded",
                "version": "2.0.0",
                "components": {
                    "database": "healthy" if db_ok else "unhealthy",
                    "vector_store": "healthy" if vector_ok else "degraded",
                    "indexed_chunks": chunks_count,
                    "scheduler": "running" if scheduler_running else "stopped"
                }
            }
        )

    # ─── Global Exception Handler ────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"[Server] Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "Internal server error"}
        )

    return app


# Create the app instance
app = create_app()
