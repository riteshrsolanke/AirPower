"""
Dynamic Retasking Service — Phase 3.
Problem Statement 26250 | SIH 2026 | Ministry of Defence
ALL DATA IS SYNTHETIC — Not connected to operational defence systems.

This service:
  1. Applies event effects to the database (mutates operational state)
  2. Identifies which assignments in the current APPROVED plan are now invalid
  3. Calls the incremental optimizer (retask_missions) for just those missions
  4. Marks the superseded plan as SUPERSEDED and links the new plan to the event
  5. Returns a RetaskResult with a full diff vs the previous plan

Supported EventTypes
--------------------
AIRCRAFT_UNSERVICEABLE  — aircraft degrades to GROUNDED / LIMITED
NEW_THREAT              — new threat zone appears, re-computes risk scores
WEATHER_CLOSURE         — base weather turns NO-GO, aircraft at that base affected
AIRSPACE_CLOSURE        — restricted zone activated, note in plan (no hard block yet)
NEW_PRIORITY_MISSION    — new P1/P2 mission injected, planned against spare resources
CREW_UNAVAILABLE        — crew member goes off-duty, advisory retask note
FEED_DEGRADED           — marks data feed as STALE/DEGRADED, reduces confidence

All event processing is synchronous (suitable for demo / SIH prototype).
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.models import (
    Aircraft, AircraftMissionStatus,
    AirBase,
    Crew,
    Mission, MissionStatus,
    ThreatZone, ThreatType,
    WeatherCondition,
    AirspaceZone, ZoneType,
    MissionPlan, PlanAssignment, PlanStatus,
    EventLog, EventType,
    DataFeed, FeedStatus,
)
from backend.app.services.optimizer import retask_missions, PlanResult

log = logging.getLogger(__name__)

# ── Return types ──────────────────────────────────────────────────────────────

@dataclass
class AssignmentChange:
    change_type: str          # "ADDED" | "REMOVED" | "RETAINED" | "REPLACED"
    mission_id: str
    mission_name: str
    prev_aircraft_id: Optional[str]
    new_aircraft_id: Optional[str]
    prev_crew_id: Optional[str]
    new_crew_id: Optional[str]
    note: str


@dataclass
class RetaskResult:
    event_id: str
    event_type: str
    affected_resource: str
    previous_plan_id: Optional[str]
    new_plan_id: Optional[str]
    new_plan: Optional[PlanResult]
    changes: List[AssignmentChange]
    retask_triggered: bool
    retask_time_ms: int
    message: str


# ── Event effect handlers ─────────────────────────────────────────────────────

def _apply_aircraft_unserviceable(
    db: Session, payload: Dict
) -> Tuple[List[str], str]:
    """
    Mark an aircraft as LIMITED or GROUNDED.
    Returns (affected_mission_ids_in_approved_plan, affected_resource_name).
    """
    aircraft_id = payload.get("aircraft_id", "")
    new_status_str = payload.get("new_status", "GROUNDED").upper()
    reason = payload.get("reason", "Unspecified technical fault")

    ac = db.query(Aircraft).filter(Aircraft.id == aircraft_id).first()
    if not ac:
        raise ValueError(f"Aircraft not found: {aircraft_id}")

    prev_status = ac.mission_capable_status
    try:
        new_status = AircraftMissionStatus(new_status_str)
    except ValueError:
        new_status = AircraftMissionStatus.GROUNDED

    ac.mission_capable_status = new_status
    # Also bump failure_risk to reflect the event
    if new_status == AircraftMissionStatus.GROUNDED:
        ac.failure_risk = min(1.0, ac.failure_risk + 0.35)
    else:
        ac.failure_risk = min(1.0, ac.failure_risk + 0.15)
    db.commit()

    log.info("Aircraft %s: %s → %s  reason=%s", aircraft_id, prev_status, new_status, reason)
    return aircraft_id, f"{aircraft_id} ({ac.model})"


def _apply_weather_closure(
    db: Session, payload: Dict
) -> Tuple[Optional[str], str]:
    """
    Set a base's weather to NO-GO.
    Returns (base_id, affected_resource_name).
    """
    base_name = payload.get("base_name", "")
    base_id   = payload.get("base_id", "")
    reason    = payload.get("reason", "Weather below minimums")

    # Find the weather record for this base
    wx = None
    if base_id:
        wx = (db.query(WeatherCondition)
              .filter(WeatherCondition.base_id == base_id)
              .order_by(WeatherCondition.recorded_at.desc())
              .first())
    if not wx and base_name:
        wx = (db.query(WeatherCondition)
              .filter(WeatherCondition.area_label.ilike(f"%{base_name}%"))
              .order_by(WeatherCondition.recorded_at.desc())
              .first())

    if wx:
        wx.is_go = False
        wx.go_no_go_reason = reason
        wx.updated_at = datetime.utcnow()
        if not base_id and wx.base_id:
            base_id = wx.base_id
        db.commit()
        log.info("Weather NO-GO set for base=%s reason=%s", base_id or base_name, reason)
    else:
        log.warning("Weather record not found for base_id=%s base_name=%s", base_id, base_name)

    return base_id, f"Base weather: {base_name or base_id}"


def _apply_new_threat(db: Session, payload: Dict) -> str:
    """
    Insert a new ThreatZone record.
    Returns affected_resource_name.
    """
    name        = payload.get("name", f"THREAT-{datetime.utcnow().strftime('%H%M%S')}")
    threat_type = payload.get("threat_type", "SAM").upper()
    center_lat  = float(payload.get("center_lat", 0.0))
    center_lon  = float(payload.get("center_lon", 0.0))
    radius_km   = float(payload.get("radius_km", 30.0))
    severity    = int(payload.get("severity", 3))
    notes       = payload.get("notes", "Threat zone from synthetic event injection.")

    try:
        tt = ThreatType(threat_type)
    except ValueError:
        tt = ThreatType.UNKNOWN

    db.add(ThreatZone(
        name=name,
        threat_type=tt,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_km=radius_km,
        severity=min(5, max(1, severity)),
        is_active=True,
        notes=notes,
    ))
    db.commit()
    log.info("New threat zone created: %s sev=%d lat=%.2f lon=%.2f r=%.0fkm",
             name, severity, center_lat, center_lon, radius_km)
    return name


def _apply_airspace_closure(db: Session, payload: Dict) -> str:
    """
    Activate a restricted airspace zone (or create a new one).
    """
    zone_name = payload.get("name", f"CLOSURE-{datetime.utcnow().strftime('%H%M%S')}")
    geometry  = payload.get("geometry", {"type": "circle", "center": [0, 0], "radius_km": 50})
    notes     = payload.get("notes", "Airspace closed per synthetic event injection.")

    # Check if zone already exists
    existing = db.query(AirspaceZone).filter(AirspaceZone.name == zone_name).first()
    if existing:
        existing.is_active = True
    else:
        db.add(AirspaceZone(
            name=zone_name,
            zone_type=ZoneType.RESTRICTED,
            geometry=geometry,
            floor_ft=0,
            ceiling_ft=60000,
            active_from=datetime.utcnow(),
            is_active=True,
            notes=notes,
        ))
    db.commit()
    log.info("Airspace closure activated: %s", zone_name)
    return zone_name


def _apply_new_priority_mission(db: Session, payload: Dict) -> Tuple[str, str]:
    """
    Create a new high-priority mission and return (mission_id, name).
    """
    from datetime import timedelta
    name           = payload.get("name", f"MISSION-INJECT-{datetime.utcnow().strftime('%H%M%S')}")
    mission_type   = payload.get("mission_type", "CAS")
    priority       = int(payload.get("priority", 1))
    duration       = float(payload.get("estimated_duration_hours", 2.0))
    req_ac_type    = payload.get("required_aircraft_type")
    req_weapon     = payload.get("required_weapon_code")
    min_ac         = int(payload.get("min_aircraft_count", 1))
    target_area    = payload.get("target_area", {"lat": 28.0, "lon": 76.0, "radius_km": 20})
    notes          = payload.get("notes", "Mission injected via dynamic event. Synthetic data.")

    now = datetime.utcnow()
    mission = Mission(
        name=name,
        mission_type=mission_type,
        priority=priority,
        status=MissionStatus.PENDING,
        target_area=target_area,
        time_window_start=now + __import__("datetime").timedelta(minutes=30),
        time_window_end=now + __import__("datetime").timedelta(hours=duration + 2),
        estimated_duration_hours=duration,
        required_aircraft_type=req_ac_type,
        required_weapon_code=req_weapon,
        min_aircraft_count=min_ac,
        notes=notes,
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)
    log.info("New mission injected: %s P%d type=%s", name, priority, mission_type)
    return mission.id, name


def _apply_crew_unavailable(db: Session, payload: Dict) -> str:
    """Mark a crew member as unavailable."""
    crew_id = payload.get("crew_id", "")
    reason  = payload.get("reason", "Crew went off-duty")
    crew = db.query(Crew).filter(Crew.id == crew_id).first()
    if crew:
        crew.is_available = False
        crew.rest_status = "MANDATORY_REST"
        db.commit()
        log.info("Crew %s marked unavailable: %s", crew.name, reason)
        return f"{crew.name} ({crew.role})"
    raise ValueError(f"Crew not found: {crew_id}")


def _apply_feed_degraded(db: Session, payload: Dict) -> str:
    """Mark a data feed as STALE or DEGRADED."""
    feed_name  = payload.get("feed_name", "")
    new_status = payload.get("status", "DEGRADED").upper()
    confidence = float(payload.get("confidence", 0.5))

    feed = db.query(DataFeed).filter(DataFeed.name == feed_name).first()
    if feed:
        try:
            feed.status = FeedStatus(new_status)
        except ValueError:
            feed.status = FeedStatus.DEGRADED
        feed.confidence = max(0.0, min(1.0, confidence))
        feed.updated_at = datetime.utcnow()
        db.commit()
        log.info("Feed %s degraded: status=%s confidence=%.2f", feed_name, new_status, confidence)
        return f"Data feed: {feed_name}"
    raise ValueError(f"Data feed not found: {feed_name}")


# ── Identify affected assignments ─────────────────────────────────────────────

def _find_affected_missions(
    db: Session,
    approved_plan: MissionPlan,
    event_type: EventType,
    payload: Dict,
    effect_data: Any,   # what _apply_* returned
) -> Tuple[List[str], Set[str], Set[str]]:
    """
    Given an approved plan and an event, return:
      - affected_mission_ids  : missions that need to be replanned
      - locked_aircraft_ids   : aircraft safely committed to other missions
      - locked_crew_ids       : crew safely committed to other missions
    """
    all_assignments = (
        db.query(PlanAssignment)
        .filter(PlanAssignment.plan_id == approved_plan.id)
        .all()
    )

    affected_mission_ids: List[str] = []
    unaffected_aircraft: Set[str] = set()
    unaffected_crew: Set[str] = set()

    for pa in all_assignments:
        invalidated = False

        if event_type == EventType.AIRCRAFT_UNSERVICEABLE:
            # effect_data = aircraft_id
            if pa.aircraft_id == effect_data:
                invalidated = True

        elif event_type == EventType.WEATHER_CLOSURE:
            # effect_data = base_id
            if pa.aircraft_id:
                ac = db.query(Aircraft).filter(Aircraft.id == pa.aircraft_id).first()
                if ac and ac.base_id == effect_data:
                    invalidated = True

        elif event_type == EventType.NEW_THREAT:
            # All assignments are potentially impacted by a new threat;
            # flag missions whose threat score is now > 0.5
            from backend.app.services.optimizer import (
                _threat_exposure, _load_context as _lc
            )
            mission = db.query(Mission).filter(Mission.id == pa.mission_id).first()
            if mission and mission.target_area:
                from backend.app.models.models import ThreatZone
                threats = db.query(ThreatZone).filter(ThreatZone.is_active == True).all()
                t_score = _threat_exposure(
                    mission.target_area.get("lat", 0),
                    mission.target_area.get("lon", 0),
                    threats,
                )
                if t_score > 0.5:
                    invalidated = True

        elif event_type == EventType.CREW_UNAVAILABLE:
            # effect_data = crew name string; we match by crew_id from payload
            # In the payload we put crew_id
            crew_id = effect_data.split("(")[0].strip() if effect_data else ""
            # Use mission-based check: if this assignment used that crew
            if pa.crew_id and pa.crew_id == payload.get("crew_id"):
                invalidated = True

        # For NEW_PRIORITY_MISSION, AIRSPACE_CLOSURE, FEED_DEGRADED:
        # no existing assignments are invalidated; only new planning needed
        elif event_type in (
            EventType.NEW_PRIORITY_MISSION,
            EventType.AIRSPACE_CLOSURE,
            EventType.FEED_DEGRADED,
        ):
            invalidated = False

        if invalidated:
            affected_mission_ids.append(pa.mission_id)
        else:
            if pa.aircraft_id:
                unaffected_aircraft.add(pa.aircraft_id)
            if pa.crew_id:
                unaffected_crew.add(pa.crew_id)

    return affected_mission_ids, unaffected_aircraft, unaffected_crew


# ── Compute plan diff ─────────────────────────────────────────────────────────

def compute_plan_diff(
    db: Session,
    prev_plan_id: str,
    new_plan_id: str,
) -> List[AssignmentChange]:
    """
    Compare two plans assignment-by-assignment.
    Returns a list of AssignmentChange objects.
    """
    prev_assignments = {
        pa.mission_id: pa
        for pa in db.query(PlanAssignment)
        .filter(PlanAssignment.plan_id == prev_plan_id)
        .all()
    }
    new_assignments = {
        pa.mission_id: pa
        for pa in db.query(PlanAssignment)
        .filter(PlanAssignment.plan_id == new_plan_id)
        .all()
    }

    all_mission_ids = set(prev_assignments) | set(new_assignments)
    changes: List[AssignmentChange] = []

    for mid in sorted(all_mission_ids):
        mission = db.query(Mission).filter(Mission.id == mid).first()
        m_name = mission.name if mission else mid

        prev = prev_assignments.get(mid)
        new  = new_assignments.get(mid)

        if prev is None and new is not None:
            changes.append(AssignmentChange(
                change_type="ADDED",
                mission_id=mid,
                mission_name=m_name,
                prev_aircraft_id=None,
                new_aircraft_id=new.aircraft_id,
                prev_crew_id=None,
                new_crew_id=new.crew_id,
                note="Mission newly covered in retask plan.",
            ))
        elif prev is not None and new is None:
            changes.append(AssignmentChange(
                change_type="REMOVED",
                mission_id=mid,
                mission_name=m_name,
                prev_aircraft_id=prev.aircraft_id,
                new_aircraft_id=None,
                prev_crew_id=prev.crew_id,
                new_crew_id=None,
                note="Mission dropped from retask plan (resource no longer available).",
            ))
        elif (prev and new and
              (prev.aircraft_id != new.aircraft_id or prev.crew_id != new.crew_id)):
            changes.append(AssignmentChange(
                change_type="REPLACED",
                mission_id=mid,
                mission_name=m_name,
                prev_aircraft_id=prev.aircraft_id,
                new_aircraft_id=new.aircraft_id,
                prev_crew_id=prev.crew_id,
                new_crew_id=new.crew_id,
                note=f"Aircraft/crew changed due to event-driven retask.",
            ))
        else:
            changes.append(AssignmentChange(
                change_type="RETAINED",
                mission_id=mid,
                mission_name=m_name,
                prev_aircraft_id=prev.aircraft_id if prev else None,
                new_aircraft_id=new.aircraft_id if new else None,
                prev_crew_id=prev.crew_id if prev else None,
                new_crew_id=new.crew_id if new else None,
                note="Assignment unchanged.",
            ))

    return changes


# ── Main entry point ──────────────────────────────────────────────────────────

def process_event(
    db: Session,
    event_log: EventLog,
    injected_by_user_id: str,
) -> RetaskResult:
    """
    Process a single operational event:
      1. Validate payload
      2. Apply effect to DB state
      3. Identify affected plan assignments
      4. Trigger incremental reoptimisation
      5. Mark old plan SUPERSEDED, link event to new plan
      6. Return RetaskResult with diff

    All data is synthetic.
    """
    t0 = time.perf_counter()
    etype = event_log.event_type
    payload = event_log.payload or {}

    log.info("process_event: type=%s id=%s", etype.value, event_log.id)

    # ── 1. Apply effect ───────────────────────────────────────────────────────

    effect_data: Any = None
    affected_resource = ""
    new_mission_id: Optional[str] = None

    try:
        if etype == EventType.AIRCRAFT_UNSERVICEABLE:
            effect_data, affected_resource = _apply_aircraft_unserviceable(db, payload)

        elif etype == EventType.WEATHER_CLOSURE:
            effect_data, affected_resource = _apply_weather_closure(db, payload)

        elif etype == EventType.NEW_THREAT:
            effect_data = _apply_new_threat(db, payload)
            affected_resource = effect_data

        elif etype == EventType.AIRSPACE_CLOSURE:
            effect_data = _apply_airspace_closure(db, payload)
            affected_resource = effect_data

        elif etype == EventType.NEW_PRIORITY_MISSION:
            new_mission_id, affected_resource = _apply_new_priority_mission(db, payload)
            effect_data = new_mission_id

        elif etype == EventType.CREW_UNAVAILABLE:
            affected_resource = _apply_crew_unavailable(db, payload)
            effect_data = affected_resource

        elif etype == EventType.FEED_DEGRADED:
            affected_resource = _apply_feed_degraded(db, payload)
            effect_data = affected_resource

        else:
            affected_resource = "Unknown event type"

    except Exception as exc:
        log.error("Event application failed: %s", exc)
        raise

    # ── 2. Find current approved plan ─────────────────────────────────────────

    approved_plan: Optional[MissionPlan] = (
        db.query(MissionPlan)
        .filter(MissionPlan.status == PlanStatus.APPROVED)
        .order_by(MissionPlan.created_at.desc())
        .first()
    )

    # Update event log with previous plan
    if approved_plan:
        event_log.previous_plan_id = approved_plan.id
    event_log.affected_resource = affected_resource
    db.commit()

    # ── 3. Identify affected assignments ──────────────────────────────────────

    affected_mission_ids: List[str] = []
    locked_aircraft: Set[str] = set()
    locked_crew: Set[str] = set()

    if approved_plan:
        affected_mission_ids, locked_aircraft, locked_crew = _find_affected_missions(
            db, approved_plan, etype, payload, effect_data
        )

    # For new priority mission, always include it in replanning
    if new_mission_id and new_mission_id not in affected_mission_ids:
        affected_mission_ids.append(new_mission_id)

    # For events that don't invalidate existing assignments but add new missions:
    if etype in (EventType.NEW_PRIORITY_MISSION,) and approved_plan:
        # Lock everything already assigned (preserve existing plan)
        all_pa = db.query(PlanAssignment).filter(
            PlanAssignment.plan_id == approved_plan.id
        ).all()
        locked_aircraft = {pa.aircraft_id for pa in all_pa if pa.aircraft_id}
        locked_crew     = {pa.crew_id     for pa in all_pa if pa.crew_id}

    # ── 4. Retask if needed ───────────────────────────────────────────────────

    if not affected_mission_ids:
        retask_time = int((time.perf_counter() - t0) * 1000)
        log.info("No retask needed for event %s (%s)", event_log.id, etype.value)
        return RetaskResult(
            event_id=event_log.id,
            event_type=etype.value,
            affected_resource=affected_resource,
            previous_plan_id=approved_plan.id if approved_plan else None,
            new_plan_id=None,
            new_plan=None,
            changes=[],
            retask_triggered=False,
            retask_time_ms=retask_time,
            message=(
                f"Event {etype.value} applied successfully. "
                "No existing assignments were invalidated — retask not required."
            ),
        )

    base_version = approved_plan.version if approved_plan else 0
    new_plan: Optional[PlanResult] = retask_missions(
        db=db,
        mission_ids=affected_mission_ids,
        locked_aircraft_ids=locked_aircraft,
        locked_crew_ids=locked_crew,
        trigger_event_id=event_log.id,
        created_by_user_id=injected_by_user_id,
        base_plan_version=base_version,
    )

    # ── 5. Mark old plan SUPERSEDED, link event ───────────────────────────────

    changes: List[AssignmentChange] = []

    if new_plan and approved_plan:
        approved_plan.status = PlanStatus.SUPERSEDED
        event_log.resulting_plan_id = new_plan.plan_id
        event_log.replanning_time_ms = new_plan.solve_time_ms
        db.commit()

        changes = compute_plan_diff(db, approved_plan.id, new_plan.plan_id)
        log.info(
            "Plan superseded: %s → %s  changes=%d",
            approved_plan.id[:8], new_plan.plan_id[:8], len(changes),
        )

    retask_time = int((time.perf_counter() - t0) * 1000)

    # Build human-readable message
    n_affected = len(affected_mission_ids)
    n_covered  = new_plan.resource_use.get("missions_covered", 0) if new_plan else 0
    msg = (
        f"Event {etype.value} processed in {retask_time} ms. "
        f"{n_affected} mission(s) affected. "
        f"{n_covered}/{n_affected} successfully replanned. "
        f"New plan v{base_version + 1} raised for review."
        if new_plan else
        f"Event {etype.value} applied but replanning produced no feasible plan. "
        "Manual intervention may be required."
    )

    return RetaskResult(
        event_id=event_log.id,
        event_type=etype.value,
        affected_resource=affected_resource,
        previous_plan_id=approved_plan.id if approved_plan else None,
        new_plan_id=new_plan.plan_id if new_plan else None,
        new_plan=new_plan,
        changes=changes,
        retask_triggered=True,
        retask_time_ms=retask_time,
        message=msg,
    )
