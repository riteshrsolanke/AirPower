"""
FastAPI application entry point.
Air Power — Dynamic Air Operations & Resource Optimisation Decision-Support System
Problem Statement 26250 | SIH 2026 | Ministry of Defence
SYNTHETIC DATA ONLY — Not connected to operational defence systems.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.app.core.config import settings
from backend.app.db.database import engine
from backend.app.models import models

# Import routers
from backend.app.api.auth import router as auth_router
from backend.app.api.aircraft import router as aircraft_router
from backend.app.api.maintenance import router as maintenance_router
from backend.app.api.extras import (
    spares_router, alerts_router, demo_router,
    reports_router, audit_router, users_router,
    fleet_router, predictions_router
)
from backend.app.api.crew import router as crew_fatigue_router
# Phase 1: Operational data routers
from backend.app.api.ops_data import (
    bases_router, crews_router, weapons_router,
    missions_router, zones_router, weather_router, feeds_router,
)
# Phase 2: Planning router
from backend.app.api.planning import router as planning_router
# Phase 3: Events + retasking router
from backend.app.api.events import router as events_router
# Integration API
from backend.app.api.integration import router as integration_router

# ── Create all tables ─────────────────────────────────────────────────────────
models.Base.metadata.create_all(bind=engine)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Air Power — Dynamic Air Operations Decision-Support System",
    description=(
        "AI-enabled decision support for planning and dynamically retasking air operations. "
        "Problem Statement 26250 | SIH 2026 | Ministry of Defence. "
        "SYNTHETIC DATA ONLY — Not connected to operational defence systems."
    ),
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
# IMPORTANT: CORS must be added LAST (outermost) so it handles OPTIONS preflight
# before any other middleware can reject it with 400.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Open for demo; restrict in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ── Security Headers Middleware ────────────────────────────────────────────────
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    # NOTE: X-XSS-Protection is deprecated; removed per Phase 6 security hardening
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Prototype-Notice"] = "Synthetic demonstration data only - PS 26250"
    return response


# ── Global Exception Handlers ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Never expose stack traces to clients."""
    import logging
    logging.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again."},
    )


# ── Routes ─────────────────────────────────────────────────────────────────────
API_PREFIX = "/api"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(aircraft_router, prefix=API_PREFIX)
app.include_router(maintenance_router, prefix=API_PREFIX)
app.include_router(crew_fatigue_router, prefix=API_PREFIX)
app.include_router(spares_router, prefix=API_PREFIX)
app.include_router(alerts_router, prefix=API_PREFIX)
app.include_router(demo_router, prefix=API_PREFIX)
app.include_router(reports_router, prefix=API_PREFIX)
app.include_router(audit_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(fleet_router, prefix=API_PREFIX)
app.include_router(predictions_router, prefix=API_PREFIX)

# Phase 1: Operational data endpoints
app.include_router(bases_router,    prefix=API_PREFIX)
app.include_router(crews_router,    prefix=API_PREFIX)
app.include_router(weapons_router,  prefix=API_PREFIX)
app.include_router(missions_router, prefix=API_PREFIX)
app.include_router(zones_router,    prefix=API_PREFIX)
app.include_router(weather_router,  prefix=API_PREFIX)
app.include_router(feeds_router,    prefix=API_PREFIX)

# Phase 2: Planning + optimisation
app.include_router(planning_router, prefix=API_PREFIX)

# Phase 3: Events + dynamic retasking
app.include_router(events_router,   prefix=API_PREFIX)
app.include_router(integration_router)  # Prefix is already set in integration.py


# ── Health Check ───────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "disclaimer": settings.SECURITY_DISCLAIMER,
    }


import os
from fastapi.responses import FileResponse

FRONTEND_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

@app.get("/")
async def root():
    index_file = os.path.join(FRONTEND_PATH, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file)
    return {
        "message": "Air Power Dynamic Air Operations Platform API",
        "docs": "/api/docs",
        "disclaimer": settings.SECURITY_DISCLAIMER,
    }

@app.get("/styles.css")
async def get_styles():
    css_file = os.path.join(FRONTEND_PATH, "styles.css")
    if os.path.isfile(css_file):
        return FileResponse(css_file, media_type="text/css")
    return JSONResponse(status_code=404, content={"detail": "Not found"})

@app.get("/app.js")
async def get_app_js():
    js_file = os.path.join(FRONTEND_PATH, "app.js")
    if os.path.isfile(js_file):
        return FileResponse(js_file, media_type="application/javascript")
    return JSONResponse(status_code=404, content={"detail": "Not found"})
