from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
from pydantic import BaseModel

from backend.app.core.deps import get_current_active_user, require_manager_or_above, require_any_authenticated
from backend.app.db.database import get_db
from backend.app.models.models import Crew, CrewDutyLog, CrewOverride, User
from backend.app.services.fatigue import compute_fatigue_score
from backend.app.services.audit import log_audit

router = APIRouter(prefix="/crew", tags=["Crew"])

def _get_ip(request):
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")

@router.get("")
async def list_crew(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_authenticated)
):
    crews = db.query(Crew).all()
    results = []
    for c in crews:
        fatigue = compute_fatigue_score(c.duty_logs)
        results.append({
            "id": c.id,
            "name": c.name,
            "rank": c.rank,
            "role": c.role,
            "base_id": c.base_id,
            "fatigue_score": fatigue["score"],
            "fatigue_status": fatigue["status"]
        })
    return results

@router.get("/{crew_id}/fatigue")
async def get_crew_fatigue(
    crew_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_authenticated)
):
    crew = db.query(Crew).filter(Crew.id == crew_id).first()
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")
        
    fatigue = compute_fatigue_score(crew.duty_logs)
    
    # Check for active override
    active_override = db.query(CrewOverride).filter(
        CrewOverride.crew_id == crew_id,
        CrewOverride.status == "APPROVED",
        CrewOverride.expires_at > datetime.utcnow()
    ).first()
    
    return {
        "crew_id": crew.id,
        "name": crew.name,
        "fatigue_score": fatigue["score"],
        "fatigue_status": fatigue["status"],
        "factors": fatigue["factors"],
        "has_active_override": active_override is not None
    }

class OverrideRequest(BaseModel):
    justification: str
    duration_hours: int = 12

@router.post("/{crew_id}/override-request")
async def request_override(
    crew_id: str,
    req: OverrideRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_above)
):
    crew = db.query(Crew).filter(Crew.id == crew_id).first()
    if not crew:
        raise HTTPException(status_code=404, detail="Crew not found")
        
    fatigue = compute_fatigue_score(crew.duty_logs)
    if fatigue["status"] != "UNFIT":
        raise HTTPException(status_code=400, detail="Crew is not UNFIT, no override needed.")
        
    override = CrewOverride(
        crew_id=crew_id,
        requested_by=current_user.id,
        justification=req.justification,
        status="PENDING",
        expires_at=datetime.utcnow() + timedelta(hours=req.duration_hours)
    )
    db.add(override)
    db.commit()
    
    log_audit(db, current_user, "CREW_OVERRIDE_REQUESTED", crew_id, "SUCCESS", _get_ip(request), {"justification": req.justification})
    
    return {"message": "Override requested", "override_id": override.id}

@router.post("/override/{override_id}/approve")
async def approve_override(
    override_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_manager_or_above)
):
    override = db.query(CrewOverride).filter(CrewOverride.id == override_id).first()
    if not override:
        raise HTTPException(status_code=404, detail="Override not found")
        
    if override.requested_by == current_user.id:
        raise HTTPException(status_code=403, detail="Four-eyes principle: Cannot approve your own request")
        
    override.status = "APPROVED"
    override.approved_by = current_user.id
    db.commit()
    
    log_audit(db, current_user, "CREW_OVERRIDE_APPROVED", override.crew_id, "SUCCESS", _get_ip(request), {"override_id": override_id})
    
    return {"message": "Override approved"}
