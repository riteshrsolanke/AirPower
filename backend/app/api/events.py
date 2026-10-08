"""
Events API — Phase 3.
Problem Statement 26250 | SIH 2026 | Ministry of Defence
ALL DATA IS SYNTHETIC — Not connected to operational defence systems.

Endpoints
---------
POST /api/events              — inject operational event → triggers retask  (Analyst+)
GET  /api/events              — list events (newest first)                   (Any auth)
GET  /api/events/{id}         — event detail + resulting plan diff           (Any auth)
GET  /api/planning/{id}/diff/{base_id}  — plan-to-plan diff (added in planning.py)

Event payload schemas are documented per EventType below.
All state mutations are logged in EventLog with full audit trail.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    require_analyst_or_above,
    require_any_authenticated,
    _log_audit,
)
from backend.app.db.database import get_db
from backend.app.models.models import (
    EventLog, EventType,
    MissionPlan, PlanAssignment, PlanStatus,
    Mission, Aircraft, Crew, User,
)
from backend.app.services.retasker import process_event, compute_plan_diff

log = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["Events & Retasking"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class InjectEventRequest(BaseModel):
    """
    Generic event injection request.

    event_type must be one of:
      AIRCRAFT_UNSERVICEABLE  | NEW_THREAT        | WEATHER_CLOSURE
      AIRSPACE_CLOSURE        | NEW_PRIORITY_MISSION | CREW_UNAVAILABLE
      FEED_DEGRADED

    payload is event-specific (see examples in /api/docs).
    """
    event_type: str = Field(..., description="One of the EventType enum values.")
    payload: Dict[str, Any] = Field(..., description="Event-specific payload (see docs).")

    @validator("event_type")
    def validate_event_type(cls, v):
        valid = [e.value for e in EventType]
        if v.upper() not in valid:
            raise ValueError(f"event_type must be one of: {valid}")
        return v.upper()


# ── Payload examples for Swagger docs ────────────────────────────────────────

PAYLOAD_EXAMPLES = {
    "AIRCRAFT_UNSERVICEABLE": {
        "aircraft_id": "DEMO-A001",
        "new_status": "GROUNDED",
        "reason": "Engine oil leak detected during preflight inspection.",
    },
    "WEATHER_CLOSURE": {
        "base_id": None,           # provide base_id OR base_name
        "base_name": "Base Alpha",
        "reason": "Severe thunderstorm — visibility < 1 km, wind > 40 kts.",
    },
    "NEW_THREAT": {
        "name": "SAM-SITE-INJECT-001",
        "threat_type": "SAM",
        "center_lat": 30.5,
        "center_lon": 76.0,
        "radius_km": 40.0,
        "severity": 4,
        "notes": "Synthetic new threat zone injected for retask demonstration.",
    },
    "AIRSPACE_CLOSURE": {
        "name": "RESTRICTED-INJECT-001",
        "geometry": {"type": "circle", "center": [29.0, 77.0], "radius_km": 60},
        "notes": "Synthetic airspace closure — NOTAM issued.",
    },
    "NEW_PRIORITY_MISSION": {
        "name": "MISSION-INJECT-ALPHA",
        "mission_type": "CAS",
        "priority": 1,
        "estimated_duration_hours": 2.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "AGM-DEMO-AS",
        "min_aircraft_count": 1,
        "target_area": {"lat": 30.5, "lon": 76.5, "radius_km": 20},
        "notes": "High-priority CAS request from synthetic ground commander.",
    },
    "CREW_UNAVAILABLE": {
        "crew_id": "<crew-uuid>",
        "reason": "Medical emergency — crew member stood down.",
    },
    "FEED_DEGRADED": {
        "feed_name": "threat_intel",
        "status": "STALE",
        "confidence": 0.4,
    },
}


# ── Serialisers ───────────────────────────────────────────────────────────────

def _event_to_dict(ev: EventLog, include_diff: bool = False, db: Session = None) -> dict:
    result = {
        "id": ev.id,
        "event_type": ev.event_type.value,
        "affected_resource": ev.affected_resource,
        "payload": ev.payload,
        "injected_by": ev.injected_by,
        "injected_at": ev.injected_at.isoformat(),
        "previous_plan_id": ev.previous_plan_id,
        "resulting_plan_id": ev.resulting_plan_id,
        "replanning_time_ms": ev.replanning_time_ms,
    }
    if include_diff and db and ev.previous_plan_id and ev.resulting_plan_id:
        try:
            changes = compute_plan_diff(db, ev.previous_plan_id, ev.resulting_plan_id)
            result["plan_diff"] = [
                {
                    "change_type": c.change_type,
                    "mission_id": c.mission_id,
                    "mission_name": c.mission_name,
                    "prev_aircraft_id": c.prev_aircraft_id,
                    "new_aircraft_id": c.new_aircraft_id,
                    "prev_crew_id": c.prev_crew_id,
                    "new_crew_id": c.new_crew_id,
                    "note": c.note,
                }
                for c in changes
            ]
        except Exception as exc:
            result["plan_diff_error"] = str(exc)
    return result


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("")
async def inject_event(
    req: InjectEventRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """
    Inject an operational event into the system.

    Immediately:
    1. Applies the event's effect to the DB (aircraft status, weather, etc.)
    2. Identifies which assignments in the current APPROVED plan are invalidated
    3. Triggers incremental re-optimisation for affected missions
    4. Marks the old approved plan as SUPERSEDED
    5. Returns the new PROPOSED plan with a full diff vs the old plan

    Requires ANALYST role or above.
    All data is synthetic.
    """
    ip = request.client.host if request.client else "unknown"

    # Create the EventLog record
    try:
        etype = EventType(req.event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {req.event_type}")

    event = EventLog(
        event_type=etype,
        payload=req.payload,
        injected_by=current_user.id,
        injected_at=datetime.utcnow(),
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    # Process event + retask
    try:
        result = process_event(db, event, injected_by_user_id=current_user.id)
    except ValueError as exc:
        # Payload validation error
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.exception("Event processing error: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Event applied but retask failed: {exc}",
        )

    # Audit
    try:
        _log_audit(
            db, current_user,
            "EVENT_INJECTED", f"event_log:{event.id}", "SUCCESS", ip,
            {
                "event_type": etype.value,
                "affected_resource": result.affected_resource,
                "retask_triggered": result.retask_triggered,
                "new_plan_id": result.new_plan_id,
            },
        )
    except Exception:
        pass

    # Build response
    response: dict = {
        "event_id":          result.event_id,
        "event_type":        result.event_type,
        "affected_resource": result.affected_resource,
        "retask_triggered":  result.retask_triggered,
        "retask_time_ms":    result.retask_time_ms,
        "message":           result.message,
        "previous_plan_id":  result.previous_plan_id,
        "disclaimer":        "All data is synthetic. Not connected to operational systems.",
    }

    if result.retask_triggered and result.new_plan:
        np = result.new_plan
        response["new_plan"] = {
            "plan_id":       np.plan_id,
            "plan_type":     np.plan_type,
            "version":       np.version,
            "coverage_pct":  np.coverage_pct,
            "risk_score":    np.risk_score,
            "resource_use":  np.resource_use,
            "summary":       np.summary,
            "assignments": [
                {
                    "mission_id":            a.mission_id,
                    "mission_name":          a.mission_name,
                    "mission_type":          a.mission_type,
                    "priority":              a.priority,
                    "aircraft_id":           a.aircraft_id,
                    "crew_name":             a.crew_name,
                    "weapon_code":           a.weapon_code,
                    "threat_exposure_score": a.threat_exposure_score,
                    "explanation":           a.explanation,
                }
                for a in np.assignments
            ],
            "dropped_missions": [
                {
                    "mission_id":   d.mission_id,
                    "mission_name": d.mission_name,
                    "priority":     d.priority,
                    "reason":       d.reason,
                }
                for d in np.dropped_missions
            ],
        }

        response["plan_diff"] = [
            {
                "change_type":      c.change_type,
                "mission_id":       c.mission_id,
                "mission_name":     c.mission_name,
                "prev_aircraft_id": c.prev_aircraft_id,
                "new_aircraft_id":  c.new_aircraft_id,
                "prev_crew_id":     c.prev_crew_id,
                "new_crew_id":      c.new_crew_id,
                "note":             c.note,
            }
            for c in result.changes
        ]

    return response


@router.get("")
async def list_events(
    event_type: Optional[str] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    List operational events, newest first.
    Optionally filter by event_type.
    """
    q = db.query(EventLog)
    if event_type:
        try:
            q = q.filter(EventLog.event_type == EventType(event_type.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    total = q.count()
    events = q.order_by(EventLog.injected_at.desc()).offset(offset).limit(limit).all()
    return {
        "events": [_event_to_dict(ev) for ev in events],
        "total": total,
        "offset": offset,
        "limit": limit,
        "valid_event_types": [e.value for e in EventType],
    }


@router.get("/payload-examples")
async def get_payload_examples(
    current_user: User = Depends(require_any_authenticated),
):
    """
    Return example payloads for each EventType.
    Useful for building the event-injection UI or testing.
    """
    return {
        "examples": PAYLOAD_EXAMPLES,
        "disclaimer": "All data is synthetic.",
    }


@router.get("/{event_id}")
async def get_event(
    event_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Return event detail including:
    - The event payload
    - Which plan it superseded
    - The resulting new plan (if retask was triggered)
    - Full assignment diff between old and new plan
    """
    ev = db.query(EventLog).filter(EventLog.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_dict(ev, include_diff=True, db=db)
