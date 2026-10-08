import time
import hmac
import hashlib
from typing import List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from backend.app.db.database import get_db
from backend.app.models.models import Aircraft, Alert

router = APIRouter(prefix="/api/integration/v1", tags=["Integration"])

# ─────────────────────────────────────────────
# API Key Configuration & Rate Limiting
# ─────────────────────────────────────────────
# In a real system, these would be in DB and hashed
VALID_API_KEYS = {
    "test-integration-key": {"scopes": ["read:aircraft", "read:alerts"], "name": "LogisticsPartner"}
}

# Simple in-memory rate limiter
RATE_LIMIT_REQUESTS = 100  # requests
RATE_LIMIT_WINDOW = 60     # seconds
_rate_limits: Dict[str, List[float]] = {}

def check_rate_limit(client_id: str):
    now = time.time()
    if client_id not in _rate_limits:
        _rate_limits[client_id] = []
    
    # Clean up old requests
    _rate_limits[client_id] = [t for t in _rate_limits[client_id] if now - t < RATE_LIMIT_WINDOW]
    
    if len(_rate_limits[client_id]) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded. Please try again later.")
    
    _rate_limits[client_id].append(now)

def verify_api_key(x_api_key: str = Header(None)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key header missing")
    
    # We use a simple constant time comparison if we hashed it, but here we just check our dict
    # using hmac.compare_digest for security against timing attacks
    valid_key = None
    for key in VALID_API_KEYS.keys():
        if hmac.compare_digest(key, x_api_key):
            valid_key = key
            break
            
    if not valid_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    check_rate_limit(valid_key)
    return VALID_API_KEYS[valid_key]

def require_scope(required_scope: str):
    def scope_checker(client_info: dict = Depends(verify_api_key)):
        if required_scope not in client_info.get("scopes", []):
            raise HTTPException(status_code=403, detail=f"Insufficient scope. Requires: {required_scope}")
        return client_info
    return scope_checker

# ─────────────────────────────────────────────
# DTOs
# ─────────────────────────────────────────────
class AircraftIntegrationSchema(BaseModel):
    id: str
    model: str
    status: str
    health_score: float
    rul_hours: float
    failure_risk: float

class AlertIntegrationSchema(BaseModel):
    id: str
    aircraft_id: Optional[str]
    severity: str
    title: str
    created_at: str

# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────
@router.get("/aircraft", response_model=List[AircraftIntegrationSchema])
def get_integration_aircraft(
    client_info: dict = Depends(require_scope("read:aircraft")),
    db: Session = Depends(get_db)
):
    aircraft = db.query(Aircraft).all()
    return [
        AircraftIntegrationSchema(
            id=a.id,
            model=a.model,
            status=a.status.value,
            health_score=a.health_score,
            rul_hours=a.rul_hours,
            failure_risk=a.failure_risk
        ) for a in aircraft
    ]

@router.get("/alerts", response_model=List[AlertIntegrationSchema])
def get_integration_alerts(
    client_info: dict = Depends(require_scope("read:alerts")),
    db: Session = Depends(get_db)
):
    alerts = db.query(Alert).filter(Alert.status == "ACTIVE").all()
    return [
        AlertIntegrationSchema(
            id=al.id,
            aircraft_id=al.aircraft_id,
            severity=al.severity.value,
            title=al.title,
            created_at=al.created_at.isoformat()
        ) for al in alerts
    ]
