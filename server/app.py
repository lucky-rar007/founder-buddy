"""
Founder Buddy — FastAPI Application.

Main web server entry point. Serves the SPA frontend, handles API routes,
and manages WebSocket connections for real-time progress updates.
"""

from __future__ import annotations

import sys
import logging
from pathlib import Path

import os
import secrets
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

from shared.version import __version__
from shared.database import init_db
from server.routes import onboarding, config, ingestion, dashboard, rag

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# RATE LIMITER (S-1) - Bounded TTL Rate Limiter
# ─────────────────────────────────────────────────────────────────────

class BoundedRateLimiter:
    """In-memory rate limiter with TTL cleanup and memory bounding."""

    def __init__(self, window_seconds: float = 60.0, max_requests: int = 60, max_ips: int = 5000):
        self.window = window_seconds
        self.max_requests = max_requests
        self.max_ips = max_ips
        self._history: dict[str, list[float]] = {}
        self._last_cleanup = time.time()

    def is_rate_limited(self, ip: str) -> bool:
        now = time.time()
        # Periodic cleanup of expired entries
        if now - self._last_cleanup > self.window:
            self._cleanup(now)

        timestamps = self._history.get(ip, [])
        valid_timestamps = [t for t in timestamps if now - t < self.window]

        if len(valid_timestamps) >= self.max_requests:
            self._history[ip] = valid_timestamps
            return True

        valid_timestamps.append(now)

        # Evict oldest entries if capacity reached
        if ip not in self._history and len(self._history) >= self.max_ips:
            keys_to_remove = list(self._history.keys())[: max(1, self.max_ips // 10)]
            for k in keys_to_remove:
                self._history.pop(k, None)

        self._history[ip] = valid_timestamps
        return False

    def _cleanup(self, now: float):
        self._last_cleanup = now
        expired_ips = [ip for ip, ts in self._history.items() if not any(now - t < self.window for t in ts)]
        for ip in expired_ips:
            self._history.pop(ip, None)


_rate_limiter = BoundedRateLimiter()


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
        version=__version__,
        lifespan=lifespan,
    )

    # CORS middleware — configurable via ALLOWED_ORIGINS env var for cloud deployments
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
        allow_headers=["Content-Type", "Authorization", "X-Requested-With", "X-API-Key"],
    )

    # ── API Key Auth Middleware (S-2) ─────────────────────────────
    _api_auth_token = os.environ.get("API_AUTH_TOKEN") or os.environ.get("FOUNDER_BUDDY_API_KEY")
    _require_auth_localhost = os.environ.get("REQUIRE_AUTH_LOCALHOST", "false").lower() in ("true", "1", "yes")

    @app.middleware("http")
    async def api_auth_middleware(request: Request, call_next):
        if _api_auth_token and request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client else "127.0.0.1"
            is_localhost = client_ip in ("127.0.0.1", "::1", "localhost")
            if not is_localhost or _require_auth_localhost:
                auth_header = request.headers.get("Authorization", "")
                token = ""
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()
                elif "X-API-Key" in request.headers:
                    token = request.headers["X-API-Key"].strip()

                if not token or not secrets.compare_digest(token, _api_auth_token):
                    return JSONResponse(
                        status_code=401,
                        content={"success": False, "error": "Unauthorized: Invalid or missing API key"}
                    )
        return await call_next(request)

    # ── CSRF Protection Middleware (F-1) ──────────────────────────
    @app.middleware("http")
    async def csrf_middleware(request: Request, call_next):
        if _env_origins and request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            referer = request.headers.get("referer")
            if origin:
                if not any(origin.startswith(allowed) for allowed in _allowed_origins):
                    return JSONResponse(
                        status_code=403,
                        content={"success": False, "error": "CSRF validation failed: Invalid Origin"}
                    )
            elif referer:
                if not any(referer.startswith(allowed) for allowed in _allowed_origins):
                    return JSONResponse(
                        status_code=403,
                        content={"success": False, "error": "CSRF validation failed: Invalid Referer"}
                    )
        return await call_next(request)

    # ── Security Headers & Static Caching Middleware (S-5, F-3) ───
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: blob:; "
            "connect-src 'self' ws: wss:;"
        )

        # F-3: Cache static assets, disable caching for dynamic/API routes
        if path.startswith(("/css/", "/js/", "/static/", "/assets/", "/logo.png")):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return response

    # ── Rate Limiting Middleware (S-1) ────────────────────────────
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client_ip = request.client.host if request.client else "127.0.0.1"
            # Exempt local single-user desktop traffic from rate limiting
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                if _rate_limiter.is_rate_limited(client_ip):
                    return JSONResponse(
                        status_code=429,
                        content={"success": False, "error": "Rate limit exceeded. Please wait a minute before retrying."}
                    )

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

    # ─── SPA Routes & Catch-All (F-2) ────────────────────────────
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
                "version": __version__,
                "components": {
                    "database": "healthy" if db_ok else "unhealthy",
                    "vector_store": "healthy" if vector_ok else "degraded",
                    "indexed_chunks": chunks_count,
                    "scheduler": "running" if scheduler_running else "stopped"
                }
            }
        )

    # Wildcard catch-all for SPA client-side deep routing (F-2)
    @app.get("/{full_path:path}")
    async def serve_spa_catchall(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"success": False, "error": "API endpoint not found"})
        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return JSONResponse(
            status_code=404,
            content={"error": "Frontend not found. Ensure server/static/index.html exists."}
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
