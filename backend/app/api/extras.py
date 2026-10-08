from backend.app.services.audit import log_audit
"""
Spare Parts, Alerts, Demo Simulation, Reports, and Admin/Audit APIs.
"""
from datetime import datetime
from typing import Optional, List
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.app.core.deps import (
    require_any_authenticated, require_manager_or_above,
    require_admin, require_analyst_or_above, get_current_active_user
)
from backend.app.db.database import get_db
from backend.app.models.models import (
    SparePart, SpareStatus, Alert, AlertStatus, AlertSeverity,
    Aircraft, AircraftStatus, AuditLog, User, Prediction, SensorReading,
    MaintenanceRecord
)
from backend.app.core.config import settings

# ─────────────────────────────────────────────────────────
# Spare Parts Router
# ─────────────────────────────────────────────────────────
spares_router = APIRouter(prefix="/spares", tags=["Spare Parts"])


def _spare_to_dict(s: SparePart) -> dict:
    available = max(0, s.current_stock - s.reserved_stock)
    return {
        "id": s.id,
        "part_number": s.part_number,
        "name": s.name,
        "category": s.category,
        "compatible_components": s.compatible_components,
        "current_stock": s.current_stock,
        "minimum_stock": s.minimum_stock,
        "reserved_stock": s.reserved_stock,
        "available_stock": available,
        "status": s.status.value,
        "unit_cost": s.unit_cost,
        "supplier": s.supplier,
        "lead_time_days": s.lead_time_days,
        "location": s.location,
        "notes": s.notes,
        "updated_at": s.updated_at.isoformat(),
    }


def _audit(db, user, action, resource, result, ip, details=None):
    log_audit(db, user, action, resource, result, ip, details)



def _get_ip(r):
    fwd = r.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (r.client.host if r.client else "unknown")


def _update_spare_status(spare: SparePart):
    available = max(0, spare.current_stock - spare.reserved_stock)
    if spare.current_stock == 0:
        spare.status = SpareStatus.OUT_OF_STOCK
    elif available < spare.minimum_stock * 0.5:
        spare.status = SpareStatus.CRITICAL
    elif available < spare.minimum_stock:
        spare.status = SpareStatus.LOW
    else:
        spare.status = SpareStatus.NORMAL


@spares_router.get("")
async def list_spares(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(SparePart)
    if status_filter:
        try:
            query = query.filter(SparePart.status == SpareStatus(status_filter.upper()))
        except ValueError:
            pass
    if search:
        query = query.filter(
            SparePart.name.ilike(f"%{search}%") |
            SparePart.part_number.ilike(f"%{search}%") |
            SparePart.category.ilike(f"%{search}%")
        )
    total = query.count()
    spares = query.offset(skip).limit(limit).all()
    return {"total": total, "spares": [_spare_to_dict(s) for s in spares]}


class StockUpdateRequest(BaseModel):
    quantity: int
    action: str  # ADD, REMOVE, RESERVE, RELEASE
    notes: Optional[str] = None


@spares_router.patch("/{spare_id}/stock")
async def update_stock(
    spare_id: str,
    req: StockUpdateRequest,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    ip = _get_ip(request)
    spare = db.query(SparePart).filter(SparePart.id == spare_id).first()
    if not spare:
        raise HTTPException(status_code=404, detail="Spare part not found")

    action = req.action.upper()
    if action == "ADD":
        spare.current_stock += req.quantity
    elif action == "REMOVE":
        if spare.current_stock < req.quantity:
            raise HTTPException(status_code=400, detail="Insufficient stock")
        spare.current_stock -= req.quantity
    elif action == "RESERVE":
        available = spare.current_stock - spare.reserved_stock
        if available < req.quantity:
            raise HTTPException(status_code=400, detail="Insufficient available stock to reserve")
        spare.reserved_stock += req.quantity
    elif action == "RELEASE":
        spare.reserved_stock = max(0, spare.reserved_stock - req.quantity)
    else:
        raise HTTPException(status_code=422, detail="Invalid action")

    _update_spare_status(spare)
    spare.updated_at = datetime.utcnow()
    db.commit()

    _audit(db, current_user, "SPARE_STOCK_UPDATED", spare.part_number, "SUCCESS", ip,
           {"action": action, "quantity": req.quantity})
    return _spare_to_dict(spare)


@spares_router.get("/predictions/shortage")
async def spare_shortage_prediction(
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Predict spare shortages based on high-risk aircraft counts."""
    high_risk_aircraft = db.query(Aircraft).filter(
        Aircraft.failure_risk > 0.6
    ).count()

    spares = db.query(SparePart).all()
    shortage_predictions = []

    for spare in spares:
        available = max(0, spare.current_stock - spare.reserved_stock)
        # Simple heuristic: each high-risk aircraft may need 1 of critical parts
        predicted_demand = high_risk_aircraft if spare.category in ["ENGINE", "HYDRAULICS"] else max(1, high_risk_aircraft // 2)
        shortage = predicted_demand > available

        if shortage or available < spare.minimum_stock:
            shortage_predictions.append({
                "part_id": spare.id,
                "part_number": spare.part_number,
                "name": spare.name,
                "available_stock": available,
                "predicted_demand": predicted_demand,
                "shortage_quantity": max(0, predicted_demand - available),
                "severity": "CRITICAL" if available == 0 else "WARNING",
                "based_on_high_risk_aircraft": high_risk_aircraft,
            })

    return {
        "high_risk_aircraft": high_risk_aircraft,
        "shortages": shortage_predictions,
        "disclaimer": "Predictive spare requirement based on synthetic demonstration data.",
    }


# ─────────────────────────────────────────────────────────
# Alerts Router
# ─────────────────────────────────────────────────────────
alerts_router = APIRouter(prefix="/alerts", tags=["Alerts"])


def _alert_to_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "aircraft_id": a.aircraft_id,
        "component_id": a.component_id,
        "severity": a.severity.value,
        "status": a.status.value,
        "title": a.title,
        "message": a.message,
        "recommended_action": a.recommended_action,
        "failure_risk": a.failure_risk,
        "created_at": a.created_at.isoformat(),
        "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
        "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
    }


@alerts_router.get("")
async def list_alerts(
    status_filter: Optional[str] = Query(None, alias="status"),
    severity: Optional[str] = None,
    aircraft_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    query = db.query(Alert)
    if status_filter:
        try:
            query = query.filter(Alert.status == AlertStatus(status_filter.upper()))
        except ValueError:
            pass
    if severity:
        try:
            query = query.filter(Alert.severity == AlertSeverity(severity.upper()))
        except ValueError:
            pass
    if aircraft_id:
        query = query.filter(Alert.aircraft_id == aircraft_id)

    total = query.count()
    alerts = query.order_by(Alert.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "alerts": [_alert_to_dict(a) for a in alerts]}


class AlertUpdateRequest(BaseModel):
    status: str  # READ, ACKNOWLEDGED, RESOLVED


@alerts_router.patch("/{alert_id}")
async def update_alert(
    alert_id: str,
    req: AlertUpdateRequest,
    request: Request,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    ip = _get_ip(request)
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    try:
        new_status = AlertStatus(req.status.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid status")

    alert.status = new_status
    if new_status == AlertStatus.ACKNOWLEDGED:
        alert.acknowledged_by = current_user.id
        alert.acknowledged_at = datetime.utcnow()
    elif new_status == AlertStatus.RESOLVED:
        alert.resolved_at = datetime.utcnow()

    db.commit()
    return _alert_to_dict(alert)


# ─────────────────────────────────────────────────────────
# Demo Simulation Router
# ─────────────────────────────────────────────────────────
demo_router = APIRouter(prefix="/demo", tags=["Demo"])


class DemoStartRequest(BaseModel):
    aircraft_id: str
    anomaly_type: str = "engine_anomaly"  # normal, engine_anomaly, hydraulic_anomaly, complete_failure


class DemoStepRequest(BaseModel):
    aircraft_id: str


@demo_router.post("/start")
async def start_demo(
    req: DemoStartRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Start a simulation for an aircraft."""
    ip = _get_ip(request)
    aircraft = db.query(Aircraft).filter(Aircraft.id == req.aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    from backend.app.services.simulation import start_simulation
    start_simulation(req.aircraft_id, req.anomaly_type)

    _audit(db, current_user, "DEMO_STARTED", req.aircraft_id, "SUCCESS", ip,
           {"anomaly_type": req.anomaly_type})
    return {"message": f"Simulation started for {req.aircraft_id}", "anomaly_type": req.anomaly_type}


@demo_router.post("/step")
async def advance_step(
    req: DemoStepRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Advance simulation by one step — returns sensor data + prediction."""
    from backend.app.services.simulation import advance_simulation_step, get_simulation_state
    state = get_simulation_state(req.aircraft_id)
    if not state or not state.get("running"):
        raise HTTPException(status_code=400, detail="Simulation not running for this aircraft")

    result = advance_simulation_step(req.aircraft_id, db)
    return result


@demo_router.post("/stop")
async def stop_demo(
    req: DemoStepRequest,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    from backend.app.services.simulation import stop_simulation
    stop_simulation(req.aircraft_id)
    return {"message": "Simulation stopped"}


@demo_router.post("/reset")
async def reset_demo(
    req: DemoStepRequest,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Reset aircraft to healthy state."""
    ip = _get_ip(request)
    from backend.app.services.simulation import reset_simulation
    reset_simulation(req.aircraft_id)

    aircraft = db.query(Aircraft).filter(Aircraft.id == req.aircraft_id).first()
    if aircraft:
        aircraft.health_score = 95.0
        aircraft.failure_risk = 0.05
        aircraft.rul_hours = 450.0
        aircraft.status = AircraftStatus.AVAILABLE
        aircraft.updated_at = datetime.utcnow()

    # Resolve all active alerts for this aircraft
    db.query(Alert).filter(
        Alert.aircraft_id == req.aircraft_id,
        Alert.status == AlertStatus.ACTIVE,
    ).update({"status": AlertStatus.RESOLVED, "resolved_at": datetime.utcnow()})

    db.commit()
    _audit(db, current_user, "DEMO_RESET", req.aircraft_id, "SUCCESS", ip)
    return {"message": f"Aircraft {req.aircraft_id} reset to healthy state"}


@demo_router.get("/status/{aircraft_id}")
async def demo_status(
    aircraft_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    from backend.app.services.simulation import get_simulation_state
    state = get_simulation_state(aircraft_id)
    return {
        "aircraft_id": aircraft_id,
        "simulation_active": bool(state and state.get("running")),
        "current_step": state.get("step", 0) if state else 0,
        "anomaly_type": state.get("anomaly_type", "none") if state else "none",
    }


# ─────────────────────────────────────────────────────────
# Reports Router
# ─────────────────────────────────────────────────────────
reports_router = APIRouter(prefix="/reports", tags=["Reports"])


@reports_router.get("/fleet-health")
async def fleet_health_report(
    format: str = Query("json", regex="^(json|csv)$"),
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Generate fleet health report from database."""
    aircraft_list = db.query(Aircraft).all()

    data = {
        "report_type": "Fleet Health Report",
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": current_user.username,
        "disclaimer": settings.SECURITY_DISCLAIMER,
        "ml_disclaimer": settings.ML_DISCLAIMER,
        "summary": {
            "total": len(aircraft_list),
            "available": sum(1 for a in aircraft_list if a.status == AircraftStatus.AVAILABLE),
            "maintenance": sum(1 for a in aircraft_list if a.status == AircraftStatus.MAINTENANCE),
            "warning": sum(1 for a in aircraft_list if a.status == AircraftStatus.WARNING),
            "critical": sum(1 for a in aircraft_list if a.status == AircraftStatus.CRITICAL),
            "avg_health_score": round(sum(a.health_score for a in aircraft_list) / len(aircraft_list), 1) if aircraft_list else 0,
        },
        "aircraft": [
            {
                "id": a.id,
                "model": a.model,
                "status": a.status.value,
                "health_score": round(a.health_score, 1),
                "failure_risk_pct": round(a.failure_risk * 100, 1),
                "rul_hours": round(a.rul_hours, 1),
                "last_maintenance": a.last_maintenance_date.isoformat() if a.last_maintenance_date else None,
            }
            for a in aircraft_list
        ],
    }

    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "model", "status", "health_score", "failure_risk_pct", "rul_hours"])
        writer.writeheader()
        writer.writerows(data["aircraft"])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=fleet_health_report.csv"},
        )

    return data


@reports_router.get("/maintenance-summary")
async def maintenance_report(
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Maintenance summary report."""
    from backend.app.models.models import MaintenanceStatus
    records = db.query(MaintenanceRecord).all()
    return {
        "report_type": "Maintenance Summary Report",
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": current_user.username,
        "disclaimer": settings.SECURITY_DISCLAIMER,
        "summary": {
            "total": len(records),
            "planned": sum(1 for r in records if r.status == MaintenanceStatus.PLANNED),
            "active": sum(1 for r in records if r.status == MaintenanceStatus.ACTIVE),
            "completed": sum(1 for r in records if r.status == MaintenanceStatus.COMPLETED),
            "cancelled": sum(1 for r in records if r.status == MaintenanceStatus.CANCELLED),
        },
        "records": [
            {
                "id": r.id,
                "aircraft_id": r.aircraft_id,
                "title": r.title,
                "status": r.status.value,
                "priority": r.priority.value,
                "scheduled_start": r.scheduled_start.isoformat() if r.scheduled_start else None,
            }
            for r in records[:100]
        ],
    }


@reports_router.get("/spare-parts")
async def spares_report(
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Spare parts inventory report."""
    spares = db.query(SparePart).all()
    low_stock = [s for s in spares if s.status in [SpareStatus.LOW, SpareStatus.CRITICAL, SpareStatus.OUT_OF_STOCK]]
    return {
        "report_type": "Spare Parts Inventory Report",
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": current_user.username,
        "disclaimer": settings.SECURITY_DISCLAIMER,
        "summary": {
            "total_parts": len(spares),
            "low_stock_count": len(low_stock),
            "out_of_stock": sum(1 for s in spares if s.status == SpareStatus.OUT_OF_STOCK),
        },
        "inventory": [
            {
                "part_number": s.part_number,
                "name": s.name,
                "current_stock": s.current_stock,
                "available": max(0, s.current_stock - s.reserved_stock),
                "minimum_stock": s.minimum_stock,
                "status": s.status.value,
            }
            for s in spares
        ],
    }


# ─────────────────────────────────────────────────────────
# Audit Log Router
# ─────────────────────────────────────────────────────────
audit_router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@audit_router.get("")
async def list_audit_logs(
    action: Optional[str] = None,
    username: Optional[str] = None,
    result: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List audit logs — Admin only."""
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action}%"))
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username}%"))
    if result:
        query = query.filter(AuditLog.result == result.upper())

    total = query.count()
    logs = query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()

    return {
        "total": total,
        "logs": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat(),
                "username": log.username,
                "role": log.role,
                "action": log.action,
                "resource": log.resource,
                "result": log.result,
                "ip_address": log.ip_address,
                "details": log.details,
                "current_hash": log.current_hash,
                "previous_hash": log.previous_hash
            }
            for log in logs
        ],
    }

from backend.app.services.audit import verify_chain

@audit_router.get("/verify")
async def verify_audit_logs(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Phase 6: Verifies the cryptographic chain of all audit logs.
    Returns status and the exact log ID where tampering is detected (if any).
    """
    return verify_chain(db)


# ─────────────────────────────────────────────────────────
# Users/Admin Router
# ─────────────────────────────────────────────────────────
users_router = APIRouter(prefix="/users", tags=["Users"])


@users_router.get("")
async def list_users(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users — Admin only."""
    users = db.query(User).all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "username": u.username,
                "full_name": u.full_name,
                "role": u.role.value,
                "is_active": u.is_active,
                "is_locked": u.is_locked,
                "mfa_enabled": u.mfa_enabled,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]
    }


class CreateUserRequest(BaseModel):
    email: str
    username: str
    password: str
    role: str
    full_name: Optional[str] = None


@users_router.post("")
async def create_user(
    req: CreateUserRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new user — Admin only."""
    from backend.app.core.security import hash_password, validate_password_strength

    ip = _get_ip(request)
    errors = validate_password_strength(req.password)
    if errors:
        raise HTTPException(status_code=422, detail=errors)

    existing = db.query(User).filter(
        (User.email == req.email) | (User.username == req.username)
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    try:
        role = UserRole(req.role.upper())
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid role")

    user = User(
        email=req.email,
        username=req.username,
        hashed_password=hash_password(req.password),
        role=role,
        full_name=req.full_name,
    )
    db.add(user)
    db.commit()

    _audit(db, current_user, "USER_CREATED", req.username, "SUCCESS", ip, {"role": req.role})
    return {"message": f"User {req.username} created", "id": user.id}


from backend.app.models.models import UserRole


@users_router.patch("/{user_id}/toggle-lock")
async def toggle_lock(
    user_id: str,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ip = _get_ip(request)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_locked = not target.is_locked
    if not target.is_locked:
        target.failed_login_attempts = 0
        target.locked_until = None
    db.commit()
    action = "USER_LOCKED" if target.is_locked else "USER_UNLOCKED"
    _audit(db, current_user, action, target.username, "SUCCESS", ip)
    return {"locked": target.is_locked}


# Fleet stats router
fleet_router = APIRouter(prefix="/fleet", tags=["Fleet"])


@fleet_router.get("/availability")
async def fleet_availability(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Fleet availability stats and projection."""
    aircraft_list = db.query(Aircraft).all()
    total = len(aircraft_list)
    if total == 0:
        return {"error": "No aircraft in database"}

    available = sum(1 for a in aircraft_list if a.status == AircraftStatus.AVAILABLE)
    maintenance = sum(1 for a in aircraft_list if a.status == AircraftStatus.MAINTENANCE)
    warning = sum(1 for a in aircraft_list if a.status == AircraftStatus.WARNING)
    critical = sum(1 for a in aircraft_list if a.status == AircraftStatus.CRITICAL)
    grounded = sum(1 for a in aircraft_list if a.status == AircraftStatus.GROUNDED)

    current_availability = round(available / total * 100, 1)

    # Simple projection: maintenance coming back online, high-risk going offline
    high_risk = sum(1 for a in aircraft_list if a.failure_risk > 0.7)
    projected_unavailable = maintenance + high_risk
    projected_available = max(0, total - projected_unavailable)
    projected_availability = round(projected_available / total * 100, 1)

    # Historical trend (last 7 days simulated)
    trend = []
    for i in range(7, -1, -1):
        trend.append({
            "day": f"Day -{i}",
            "availability": round(current_availability + (i * 1.5) - 5 + (i % 3), 1),
            "projected": round(projected_availability + (i * 1.0) - 3, 1),
        })

    return {
        "total": total,
        "available": available,
        "maintenance": maintenance,
        "warning": warning,
        "critical": critical,
        "grounded": grounded,
        "current_availability_pct": current_availability,
        "projected_availability_pct": projected_availability,
        "high_risk_count": high_risk,
        "trend": trend,
        "disclaimer": "Prototype simulation — not operational fleet data.",
    }


# Predictions router
predictions_router = APIRouter(prefix="/predictions", tags=["Predictions"])


@predictions_router.get("")
async def list_predictions(
    aircraft_id: Optional[str] = None,
    limit: int = 50,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    query = db.query(Prediction)
    if aircraft_id:
        query = query.filter(Prediction.aircraft_id == aircraft_id)
    preds = query.order_by(Prediction.generated_at.desc()).limit(limit).all()
    return {
        "predictions": [
            {
                "id": p.id,
                "aircraft_id": p.aircraft_id,
                "generated_at": p.generated_at.isoformat(),
                "anomaly_score": p.anomaly_score,
                "failure_risk": p.failure_risk,
                "failure_risk_pct": round(p.failure_risk * 100, 1) if p.failure_risk else 0,
                "risk_level": p.risk_level.value if p.risk_level else "UNKNOWN",
                "rul_hours": p.rul_hours,
                "health_score": p.health_score,
                "contributing_factors": p.contributing_factors,
                "disclaimer": p.disclaimer,
            }
            for p in preds
        ]
    }
