from backend.app.services.audit import log_audit
"""
Aircraft API routes — CRUD operations with RBAC.
All aircraft data is SYNTHETIC for demonstration purposes.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    get_current_active_user, require_manager_or_above, require_admin,
    require_any_authenticated, require_analyst_or_above
)
from backend.app.db.database import get_db
from backend.app.models.models import (
    Aircraft, AircraftComponent, SensorReading, Prediction,
    Alert, AlertStatus, AircraftStatus, User, AuditLog
)
from backend.app.ml.predictor import get_ml_model

router = APIRouter(prefix="/aircraft", tags=["Aircraft"])


def _audit(db, user, action, resource, result, ip, details=None):
    log_audit(db, user, action, resource, result, ip, details)



def _get_ip(request):
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def _aircraft_to_dict(a: Aircraft) -> dict:
    return {
        "id": a.id,
        "model": a.model,
        "serial_number": a.serial_number,
        "manufacture_year": a.manufacture_year,
        "status": a.status.value,
        "health_score": round(a.health_score, 1),
        "failure_risk": round(a.failure_risk, 3),
        "failure_risk_pct": round(a.failure_risk * 100, 1),
        "rul_hours": round(a.rul_hours, 1),
        "total_flight_hours": round(a.total_flight_hours, 0),
        "last_maintenance_date": a.last_maintenance_date.isoformat() if a.last_maintenance_date else None,
        "next_maintenance_date": a.next_maintenance_date.isoformat() if a.next_maintenance_date else None,
        "location": a.location,
        "notes": a.notes,
        "created_at": a.created_at.isoformat(),
        "updated_at": a.updated_at.isoformat(),
        "active_alerts": len([al for al in a.alerts if al.status == AlertStatus.ACTIVE]),
        # Phase 1: operational readiness fields
        "mission_capable_status": a.mission_capable_status.value if a.mission_capable_status else "CAPABLE",
        "base_id": a.base_id,
        "range_km": a.range_km,
        "fuel_capacity": a.fuel_capacity,
        "payload_capacity": a.payload_capacity,
    }


@router.get("")
async def list_aircraft(
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List all aircraft with optional status/search filters."""
    query = db.query(Aircraft)

    if status_filter:
        try:
            s = AircraftStatus(status_filter.upper())
            query = query.filter(Aircraft.status == s)
        except ValueError:
            pass

    if search:
        query = query.filter(
            Aircraft.id.ilike(f"%{search}%") |
            Aircraft.model.ilike(f"%{search}%") |
            Aircraft.serial_number.ilike(f"%{search}%")
        )

    total = query.count()
    aircraft_list = query.offset(skip).limit(limit).all()
    return {
        "total": total,
        "aircraft": [_aircraft_to_dict(a) for a in aircraft_list],
    }


@router.get("/statistics")
async def fleet_statistics(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Fleet-level statistics for dashboard."""
    all_aircraft = db.query(Aircraft).all()
    total = len(all_aircraft)
    available = sum(1 for a in all_aircraft if a.status == AircraftStatus.AVAILABLE)
    maintenance = sum(1 for a in all_aircraft if a.status == AircraftStatus.MAINTENANCE)
    warning = sum(1 for a in all_aircraft if a.status == AircraftStatus.WARNING)
    critical = sum(1 for a in all_aircraft if a.status == AircraftStatus.CRITICAL)
    grounded = sum(1 for a in all_aircraft if a.status == AircraftStatus.GROUNDED)

    availability_pct = round((available / total * 100) if total > 0 else 0, 1)

    active_alerts = db.query(Alert).filter(Alert.status == AlertStatus.ACTIVE).count()

    high_risk = [a for a in all_aircraft if a.failure_risk > 0.7]
    avg_health = round(sum(a.health_score for a in all_aircraft) / total, 1) if total else 0

    return {
        "total": total,
        "available": available,
        "maintenance": maintenance,
        "warning": warning,
        "critical": critical,
        "grounded": grounded,
        "availability_pct": availability_pct,
        "active_alerts": active_alerts,
        "high_risk_count": len(high_risk),
        "avg_health_score": avg_health,
        "disclaimer": "Prototype simulation — not operational data.",
    }


@router.get("/{aircraft_id}")
async def get_aircraft(
    aircraft_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Get detailed aircraft info including components."""
    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail=f"Aircraft {aircraft_id} not found")

    result = _aircraft_to_dict(aircraft)
    result["components"] = [
        {
            "id": c.id,
            "name": c.name,
            "component_type": c.component_type,
            "status": c.status.value,
            "health_score": round(c.health_score, 1),
            "failure_risk": round(c.failure_risk, 3),
            "rul_hours": round(c.rul_hours, 1),
            "operating_hours": round(c.operating_hours, 0),
            "anomaly_score": round(c.anomaly_score, 3),
            "last_maintenance_date": c.last_maintenance_date.isoformat() if c.last_maintenance_date else None,
            "notes": c.notes,
        }
        for c in aircraft.components
    ]

    # Latest prediction
    latest_pred = (
        db.query(Prediction)
        .filter(Prediction.aircraft_id == aircraft_id)
        .order_by(Prediction.generated_at.desc())
        .first()
    )
    if latest_pred:
        result["latest_prediction"] = {
            "generated_at": latest_pred.generated_at.isoformat(),
            "failure_risk": latest_pred.failure_risk,
            "risk_level": latest_pred.risk_level.value,
            "rul_hours": latest_pred.rul_hours,
            "rul_low": latest_pred.rul_low,
            "rul_high": latest_pred.rul_high,
            "confidence_level": latest_pred.confidence_level,
            "uncertainty_label": latest_pred.uncertainty_label,
            "health_score": latest_pred.health_score,
            "contributing_factors": latest_pred.contributing_factors,
            "disclaimer": latest_pred.disclaimer,
        }

    # Active alerts
    result["active_alerts_list"] = [
        {
            "id": al.id,
            "severity": al.severity.value,
            "title": al.title,
            "message": al.message,
            "recommended_action": al.recommended_action,
            "created_at": al.created_at.isoformat(),
            "factors": al.factors,
        }
        for al in aircraft.alerts if al.status == AlertStatus.ACTIVE
    ]

    return result


@router.get("/{aircraft_id}/sensors")
async def get_sensor_history(
    aircraft_id: str,
    limit: int = Query(50, le=500),
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Get recent sensor readings for an aircraft."""
    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    readings = (
        db.query(SensorReading)
        .filter(SensorReading.aircraft_id == aircraft_id)
        .order_by(SensorReading.timestamp.desc())
        .limit(limit)
        .all()
    )
    readings.reverse()  # Chronological order for charts

    return {
        "aircraft_id": aircraft_id,
        "readings": [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "engine_temperature": r.engine_temperature,
                "vibration": r.vibration,
                "oil_pressure": r.oil_pressure,
                "fuel_consumption": r.fuel_consumption,
                "hydraulic_pressure": r.hydraulic_pressure,
                "operating_hours": r.operating_hours,
                "anomaly_flag": r.anomaly_flag,
                "simulation_step": r.simulation_step,
            }
            for r in readings
        ],
    }


@router.post("/{aircraft_id}/predict")
async def run_prediction(
    aircraft_id: str,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Run ML prediction for an aircraft using latest sensor data."""
    ip = _get_ip(request)
    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    latest_reading = (
        db.query(SensorReading)
        .filter(SensorReading.aircraft_id == aircraft_id)
        .order_by(SensorReading.timestamp.desc())
        .first()
    )

    if not latest_reading:
        raise HTTPException(status_code=422, detail="No sensor data available for prediction")

    sensor_data = {
        "engine_temperature": latest_reading.engine_temperature,
        "vibration": latest_reading.vibration,
        "oil_pressure": latest_reading.oil_pressure,
        "fuel_consumption": latest_reading.fuel_consumption,
        "hydraulic_pressure": latest_reading.hydraulic_pressure,
        "operating_hours": latest_reading.operating_hours,
    }

    try:
        model = get_ml_model()
        result = model.predict(sensor_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML prediction failed: {str(e)}")

    # Store prediction
    from backend.app.models.models import Prediction, RiskLevel
    pred = Prediction(
        aircraft_id=aircraft_id,
        failure_risk=result["failure_risk"],
        risk_level=RiskLevel(result["risk_level"]),
        rul_hours=result["rul_hours"],
        rul_low=result.get("rul_low"),
        rul_high=result.get("rul_high"),
        confidence_level=result.get("confidence_level"),
        uncertainty_label=result.get("uncertainty_label"),
        health_score=result["health_score"],
        anomaly_score=result["anomaly_score"],
        contributing_factors=result["contributing_factors"],
        generated_by=current_user.id,
    )
    db.add(pred)

    # Update aircraft
    aircraft.health_score = result["health_score"]
    aircraft.failure_risk = result["failure_risk"]
    aircraft.rul_hours = result["rul_hours"]
    db.commit()

    _audit(db, current_user, "PREDICTION_GENERATED", aircraft_id, "SUCCESS", ip,
           {"risk_level": result["risk_level"], "failure_risk": result["failure_risk"]})

    result["aircraft_id"] = aircraft_id
    return result


class AircraftUpdateRequest(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    location: Optional[str] = None


@router.patch("/{aircraft_id}")
async def update_aircraft(
    aircraft_id: str,
    update: AircraftUpdateRequest,
    request: Request,
    current_user: User = Depends(require_manager_or_above),
    db: Session = Depends(get_db),
):
    """Update aircraft status/notes (Manager+)."""
    ip = _get_ip(request)
    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    if update.status:
        try:
            aircraft.status = AircraftStatus(update.status.upper())
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid status")

    if update.notes is not None:
        aircraft.notes = update.notes

    if update.location is not None:
        aircraft.location = update.location

    aircraft.updated_at = datetime.utcnow()
    db.commit()
    _audit(db, current_user, "AIRCRAFT_UPDATED", aircraft_id, "SUCCESS", ip, update.dict(exclude_none=True))
    return _aircraft_to_dict(aircraft)

class WhatIfRequest(BaseModel):
    extra_hours: int
    profile: str = "NORMAL"

@router.post("/{aircraft_id}/whatif")
async def run_whatif_scenario(
    aircraft_id: str,
    req_body: WhatIfRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Run a what-if scenario projecting aircraft health into the future."""
    ip = _get_ip(request)
    if not (1 <= req_body.extra_hours <= 500):
        raise HTTPException(status_code=422, detail="extra_hours must be between 1 and 500")
    if req_body.profile not in ["NORMAL", "HIGH_STRESS", "LOW_STRESS"]:
        raise HTTPException(status_code=422, detail="profile must be NORMAL, HIGH_STRESS, or LOW_STRESS")

    aircraft = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not aircraft:
        raise HTTPException(status_code=404, detail="Aircraft not found")

    latest_reading = (
        db.query(SensorReading)
        .filter(SensorReading.aircraft_id == aircraft_id)
        .order_by(SensorReading.timestamp.desc())
        .first()
    )
    if not latest_reading:
        raise HTTPException(status_code=422, detail="No sensor data available for projection")

    import random
    from backend.app.ml.predictor import get_ml_model
    model = get_ml_model()

    timeline = []
    
    # Base values from latest reading
    base_temp = latest_reading.engine_temperature
    base_vib = latest_reading.vibration
    base_oil = latest_reading.oil_pressure
    base_fuel = latest_reading.fuel_consumption
    base_hyd = latest_reading.hydraulic_pressure
    base_hours = latest_reading.operating_hours

    # Stress factors
    stress_mult = 1.0
    if req_body.profile == "HIGH_STRESS": stress_mult = 1.5
    if req_body.profile == "LOW_STRESS": stress_mult = 0.5

    warning_hour = None
    critical_hour = None
    most_likely_components = set()

    step_size = 10
    steps = int(req_body.extra_hours / step_size)
    if steps == 0:
        steps = 1
        step_size = req_body.extra_hours

    for step in range(1, steps + 1):
        hr_offset = step * step_size
        severity = min(1.0, (hr_offset / 500.0) * stress_mult)
        noise = lambda std: random.gauss(0, std)

        # Simple generic degradation for what-if
        sim_temp = base_temp + severity * 15 + noise(1)
        sim_vib = base_vib + severity * 1.5 + noise(0.1)
        sim_oil = base_oil - severity * 10 + noise(1)
        sim_fuel = base_fuel + severity * 30 + noise(5)
        sim_hyd = base_hyd - severity * 300 + noise(20)
        
        sensor_data = {
            "engine_temperature": round(sim_temp, 2),
            "vibration": round(sim_vib, 3),
            "oil_pressure": round(sim_oil, 2),
            "fuel_consumption": round(sim_fuel, 1),
            "hydraulic_pressure": round(sim_hyd, 1),
            "operating_hours": round(base_hours + hr_offset, 1),
        }
        
        pred = model.predict(sensor_data)
        
        timeline.append({
            "hour": hr_offset,
            "sensors": sensor_data,
            "risk_class": pred["risk_level"],
            "anomaly_score": pred["anomaly_score"],
            "rul_hours": pred["rul_hours"],
            "rul_low": pred.get("rul_low"),
            "rul_high": pred.get("rul_high")
        })

        if pred["risk_level"] == "WARNING" and warning_hour is None:
            warning_hour = hr_offset
        if pred["risk_level"] == "CRITICAL" and critical_hour is None:
            critical_hour = hr_offset
            
        for f in pred.get("contributing_factors", []):
            if f["severity"] in ["WARNING", "CRITICAL"]:
                most_likely_components.add(f["sensor"])

    _audit(db, current_user, "WHATIF_SCENARIO_RUN", aircraft_id, "SUCCESS", ip, req_body.dict())

    # Build recommendation
    if critical_hour:
        rec = f"Safe for {max(0, critical_hour - 20)} h; schedule maintenance before hour {critical_hour}."
    elif warning_hour:
        rec = f"Safe for {warning_hour} h; monitor closely afterwards."
    else:
        rec = f"Safe for {req_body.extra_hours} h under {req_body.profile} profile."

    return {
        "timeline": timeline,
        "warning_hour": warning_hour,
        "critical_hour": critical_hour,
        "most_likely_components": list(most_likely_components),
        "spare_parts_needed": ["ENG-FILTER-001", "HYD-SEAL-001"] if most_likely_components else [],
        "recommendation": rec
    }
