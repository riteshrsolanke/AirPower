from backend.app.services.audit import log_audit
"""
Maintenance API routes — CRUD with RBAC.
"""
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    require_any_authenticated, require_manager_or_above, require_admin
)
from backend.app.db.database import get_db
from backend.app.models.models import (
    MaintenanceRecord, MaintenanceStatus, MaintenancePriority,
    Aircraft, AircraftStatus, User, AuditLog
)

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


def _audit(db, user, action, resource, result, ip, details=None):
    log_audit(db, user, action, resource, result, ip, details)



def _get_ip(r):
    fwd = r.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "unknown")


def _record_to_dict(r: MaintenanceRecord) -> dict:
    return {
        "id": r.id,
        "aircraft_id": r.aircraft_id,
        "component_id": r.component_id,
        "title": r.title,
        "description": r.description,
        "status": r.status.value,
        "priority": r.priority.value,
        "assigned_to": r.assigned_to,
        "scheduled_start": r.scheduled_start.isoformat() if r.scheduled_start else None,
        "scheduled_end": r.scheduled_end.isoformat() if r.scheduled_end else None,
        "actual_start": r.actual_start.isoformat() if r.actual_start else None,
        "actual_end": r.actual_end.isoformat() if r.actual_end else None,
        "estimated_duration_hours": r.estimated_duration_hours,
        "spare_parts_required": r.spare_parts_required,
        "notes": r.notes,
        "created_at": r.created_at.isoformat(),
    }


class CreateMaintenanceRequest(BaseModel):
    aircraft_id: str
    component_id: Optional[str] = None
    title: str
    description: Optional[str] = None
    priority: str = "MEDIUM"
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    estimated_duration_hours: float = 4.0
    assigned_to: Optional[str] = None
    spare_parts_required: Optional[List[str]] = None
    notes: Optional[str] = None


class UpdateMaintenanceRequest(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    actual_start: Optional[str] = None
    actual_end: Optional[str] = None


@router.get("")
async def list_maintenance(
    status_filter: Optional[str] = Query(None, alias="status"),
    aircraft_id: Optional[str] = None,
    priority: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List maintenance records with filters."""
    query = db.query(MaintenanceRecord)

    if status_filter:
        try:
            query = query.filter(MaintenanceRecord.status == MaintenanceStatus(status_filter.upper()))
        except ValueError:
            pass

    if aircraft_id:
        query = query.filter(MaintenanceRecord.aircraft_id == aircraft_id)

    if priority:
        try:
            query = query.filter(MaintenanceRecord.priority == MaintenancePriority(priority.upper()))
        except ValueError:
            pass

    total = query.count()
    records = query.order_by(MaintenanceRecord.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "records": [_record_to_dict(r) for r in records]}


@router.post("")
async def create_maintenance(
    req: CreateMaintenanceRequest,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Create a maintenance record (Manager+)."""
    ip = _get_ip(request)

    aircraft = db.query(Aircraft).filter(Aircraft.id == req.aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    try:
        priority = MaintenancePriority(req.priority.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid priority")

    scheduled_start = datetime.fromisoformat(req.scheduled_start) if req.scheduled_start else datetime.utcnow()
    scheduled_end = datetime.fromisoformat(req.scheduled_end) if req.scheduled_end else None

    record = MaintenanceRecord(
        aircraft_id=req.aircraft_id,
        component_id=req.component_id,
        title=req.title,
        description=req.description,
        priority=priority,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        estimated_duration_hours=req.estimated_duration_hours,
        assigned_to=req.assigned_to,
        spare_parts_required=req.spare_parts_required,
        notes=req.notes,
        created_by=current_user.id,
    )
    db.add(record)

    # Update aircraft status
    aircraft.status = AircraftStatus.MAINTENANCE
    aircraft.updated_at = datetime.utcnow()

    db.commit()
    _audit(db, current_user, "MAINTENANCE_CREATED", req.aircraft_id, "SUCCESS", ip,
           {"title": req.title, "priority": req.priority})
    return _record_to_dict(record)


@router.get("/{record_id}")
async def get_maintenance(
    record_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    return _record_to_dict(record)


@router.patch("/{record_id}")
async def update_maintenance(
    record_id: str,
    req: UpdateMaintenanceRequest,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Update a maintenance record."""
    ip = _get_ip(request)
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")

    if req.status:
        try:
            record.status = MaintenanceStatus(req.status.upper())
            if record.status == MaintenanceStatus.ACTIVE and not record.actual_start:
                record.actual_start = datetime.utcnow()
            if record.status == MaintenanceStatus.COMPLETED and not record.actual_end:
                record.actual_end = datetime.utcnow()
                # Update aircraft next maintenance date
                aircraft = db.query(Aircraft).filter(Aircraft.id == record.aircraft_id).first()
                if aircraft:
                    aircraft.last_maintenance_date = datetime.utcnow()
                    aircraft.status = AircraftStatus.AVAILABLE
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid status")

    if req.priority:
        record.priority = MaintenancePriority(req.priority.upper())
    if req.assigned_to is not None:
        record.assigned_to = req.assigned_to
    if req.notes is not None:
        record.notes = req.notes

    record.updated_at = datetime.utcnow()
    db.commit()
    _audit(db, current_user, "MAINTENANCE_UPDATED", record_id, "SUCCESS", ip,
           {"new_status": req.status})
    return _record_to_dict(record)


@router.delete("/{record_id}")
async def cancel_maintenance(
    record_id: str,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Cancel a maintenance record."""
    ip = _get_ip(request)
    record = db.query(MaintenanceRecord).filter(MaintenanceRecord.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Maintenance record not found")
    if record.status == MaintenanceStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot cancel a completed maintenance record")

    record.status = MaintenanceStatus.CANCELLED
    record.updated_at = datetime.utcnow()
    db.commit()
    _audit(db, current_user, "MAINTENANCE_CANCELLED", record_id, "SUCCESS", ip)
    return {"message": "Maintenance record cancelled"}


@router.get("/recommendations/priority")
async def maintenance_priority(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """AI-driven maintenance priority recommendations (synthetic demo)."""
    from backend.app.models.models import Aircraft as AircraftModel
    aircraft_list = db.query(AircraftModel).all()

    recommendations = []
    for a in aircraft_list:
        if a.failure_risk > 0.3 or a.health_score < 80:
            if a.failure_risk > 0.75:
                priority = "CRITICAL"
            elif a.failure_risk > 0.55:
                priority = "HIGH"
            elif a.failure_risk > 0.35:
                priority = "MEDIUM"
            else:
                priority = "LOW"

            recommendations.append({
                "aircraft_id": a.id,
                "model": a.model,
                "health_score": round(a.health_score, 1),
                "failure_risk": round(a.failure_risk * 100, 1),
                "rul_hours": round(a.rul_hours, 1),
                "recommended_priority": priority,
                "reason": f"Health: {a.health_score:.0f}%, Risk: {a.failure_risk*100:.0f}%, RUL: {a.rul_hours:.0f}h",
                "disclaimer": "Prototype maintenance planning recommendation.",
            })

    recommendations.sort(key=lambda x: x["failure_risk"], reverse=True)
    return {
        "recommendations": recommendations[:20],
        "disclaimer": "Prototype maintenance planning recommendation — not an operational military schedule.",
    }
