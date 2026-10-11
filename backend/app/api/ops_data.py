"""
Operational Data API — Phase 1.
Provides read endpoints for:
  - Air Bases
  - Crews
  - Weapon Types & Inventories
  - Missions
  - Airspace Zones
  - Threat Zones
  - Weather Conditions
  - Data Feeds

All data is SYNTHETIC — not connected to operational defence systems.
Every endpoint requires authentication (Viewer+).
Write operations require Analyst+ or Manager+.
"""
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    require_any_authenticated, require_analyst_or_above,
    require_manager_or_above,
)
from backend.app.db.database import get_db
from backend.app.services.fusion import ingest_feed
from backend.app.models.models import (
    AirBase, Crew, WeaponType, WeaponInventory,
    Mission, MissionStatus,
    AirspaceZone, ZoneType,
    ThreatZone, ThreatType,
    WeatherCondition,
    DataFeed, FeedStatus,
    AuditLog, User,
)

# ── Sub-routers (all mounted in main.py under /api) ───────────────────────────

bases_router    = APIRouter(prefix="/bases",    tags=["Operational - Bases"])
crews_router    = APIRouter(prefix="/crews",    tags=["Operational - Crews"])
weapons_router  = APIRouter(prefix="/weapons",  tags=["Operational - Weapons"])
missions_router = APIRouter(prefix="/missions", tags=["Operational - Missions"])
zones_router    = APIRouter(prefix="/zones",    tags=["Operational - Airspace & Threats"])
weather_router  = APIRouter(prefix="/weather",  tags=["Operational - Weather"])
feeds_router    = APIRouter(prefix="/feeds",    tags=["Operational - Data Feeds"])


# ── Serialisers ───────────────────────────────────────────────────────────────

def _base_to_dict(b: AirBase) -> dict:
    return {
        "id": b.id,
        "name": b.name,
        "icao_code": b.icao_code,
        "latitude": b.latitude,
        "longitude": b.longitude,
        "elevation_ft": b.elevation_ft,
        "runway_status": b.runway_status,
        "max_aircraft_capacity": b.max_aircraft_capacity,
        "notes": b.notes,
        "created_at": b.created_at.isoformat(),
    }


def _crew_to_dict(c: Crew) -> dict:
    duty_remaining = max(0.0, c.max_duty_hours - c.duty_hours_used)
    return {
        "id": c.id,
        "name": c.name,
        "rank": c.rank,
        "role": c.role,
        "aircraft_qualifications": c.aircraft_qualifications or [],
        "duty_hours_used": round(c.duty_hours_used, 1),
        "max_duty_hours": c.max_duty_hours,
        "duty_hours_remaining": round(duty_remaining, 1),
        "rest_status": c.rest_status,
        "is_available": c.is_available,
        "base_id": c.base_id,
        "notes": c.notes,
    }


def _weapon_type_to_dict(w: WeaponType) -> dict:
    return {
        "id": w.id,
        "code": w.code,
        "name": w.name,
        "category": w.category,
        "weight_kg": w.weight_kg,
        "range_km": w.range_km,
        "notes": w.notes,
    }


def _inventory_to_dict(inv: WeaponInventory) -> dict:
    available = max(0, inv.quantity - inv.reserved_quantity)
    return {
        "id": inv.id,
        "base_id": inv.base_id,
        "weapon_type_id": inv.weapon_type_id,
        "weapon_code": inv.weapon_type.code if inv.weapon_type else None,
        "weapon_name": inv.weapon_type.name if inv.weapon_type else None,
        "quantity": inv.quantity,
        "reserved_quantity": inv.reserved_quantity,
        "available_quantity": available,
        "updated_at": inv.updated_at.isoformat(),
    }


def _mission_to_dict(m: Mission) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "mission_type": m.mission_type,
        "priority": m.priority,
        "status": m.status.value,
        "target_area": m.target_area,
        "time_window_start": m.time_window_start.isoformat() if m.time_window_start else None,
        "time_window_end":   m.time_window_end.isoformat()   if m.time_window_end   else None,
        "estimated_duration_hours": m.estimated_duration_hours,
        "required_aircraft_type": m.required_aircraft_type,
        "required_weapon_code":   m.required_weapon_code,
        "min_aircraft_count": m.min_aircraft_count,
        "distance_km": m.distance_km,
        "required_payload": m.required_payload,
        "notes": m.notes,
        "created_at": m.created_at.isoformat(),
    }


def _airspace_to_dict(z: AirspaceZone) -> dict:
    return {
        "id": z.id,
        "name": z.name,
        "zone_type": z.zone_type.value,
        "geometry": z.geometry,
        "floor_ft": z.floor_ft,
        "ceiling_ft": z.ceiling_ft,
        "active_from": z.active_from.isoformat() if z.active_from else None,
        "active_until": z.active_until.isoformat() if z.active_until else None,
        "is_active": z.is_active,
        "notes": z.notes,
    }


def _threat_to_dict(t: ThreatZone) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "threat_type": t.threat_type.value,
        "center_lat": t.center_lat,
        "center_lon": t.center_lon,
        "radius_km": t.radius_km,
        "severity": t.severity,
        "is_active": t.is_active,
        "detected_at": t.detected_at.isoformat(),
        "notes": t.notes,
    }


def _weather_to_dict(w: WeatherCondition) -> dict:
    return {
        "id": w.id,
        "base_id": w.base_id,
        "area_label": w.area_label,
        "recorded_at": w.recorded_at.isoformat(),
        "visibility_km": w.visibility_km,
        "wind_speed_kts": w.wind_speed_kts,
        "wind_direction_deg": w.wind_direction_deg,
        "ceiling_ft": w.ceiling_ft,
        "temperature_c": w.temperature_c,
        "is_go": w.is_go,
        "go_no_go_reason": w.go_no_go_reason,
        "confidence": w.confidence,
        "updated_at": w.updated_at.isoformat(),
    }


def _feed_to_dict(f: DataFeed) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "description": f.description,
        "update_interval_seconds": f.update_interval_seconds,
        "last_update": f.last_update.isoformat() if f.last_update else None,
        "status": f.status.value,
        "confidence": round(f.confidence, 3),
        "requires_signature": f.requires_signature,
        "notes": f.notes,
        "updated_at": f.updated_at.isoformat(),
    }


# ── Bases ─────────────────────────────────────────────────────────────────────

@bases_router.get("")
async def list_bases(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List all synthetic air bases."""
    bases = db.query(AirBase).order_by(AirBase.name).all()
    return {"bases": [_base_to_dict(b) for b in bases], "total": len(bases)}


@bases_router.get("/{base_id}")
async def get_base(
    base_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Get a single base with its weapon inventory and weather."""
    base = db.query(AirBase).filter(AirBase.id == base_id).first()
    if not base:
        raise HTTPException(status_code=404, detail="Base not found")
    result = _base_to_dict(base)
    result["weapon_inventory"] = [_inventory_to_dict(inv) for inv in base.weapon_inventories]
    result["weather"] = [_weather_to_dict(w) for w in base.weather_conditions]
    return result


# ── Crews ─────────────────────────────────────────────────────────────────────

@crews_router.get("")
async def list_crews(
    base_id: Optional[str] = None,
    role: Optional[str] = None,
    available_only: bool = False,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List synthetic crew records with optional filters."""
    q = db.query(Crew)
    if base_id:
        q = q.filter(Crew.base_id == base_id)
    if role:
        q = q.filter(Crew.role == role.upper())
    if available_only:
        q = q.filter(Crew.is_available == True)
    crews = q.order_by(Crew.name).all()
    return {"crews": [_crew_to_dict(c) for c in crews], "total": len(crews)}


@crews_router.get("/summary/readiness")
async def crew_readiness_summary(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Aggregate crew availability and fatigue summary."""
    crews = db.query(Crew).all()
    total = len(crews)
    available   = sum(1 for c in crews if c.is_available and c.rest_status != "MANDATORY_REST")
    fit         = sum(1 for c in crews if c.rest_status == "RESTED" and c.is_available)
    caution     = sum(1 for c in crews if c.rest_status == "FATIGUED" and c.is_available)
    unfit       = sum(1 for c in crews if c.rest_status == "MANDATORY_REST" or not c.is_available)
    fatigued    = sum(1 for c in crews if c.rest_status == "FATIGUED")
    mandatory   = sum(1 for c in crews if c.rest_status == "MANDATORY_REST")
    by_role = {}
    for c in crews:
        by_role.setdefault(c.role, {"total": 0, "available": 0})
        by_role[c.role]["total"] += 1
        if c.is_available:
            by_role[c.role]["available"] += 1
    return {
        "total": total,
        "available": available,
        "fit": fit,
        "caution": caution,
        "unfit": unfit,
        "fatigued": fatigued,
        "mandatory_rest": mandatory,
        "by_role": by_role,
    }


# ── Weapons ───────────────────────────────────────────────────────────────────

@weapons_router.get("/types")
async def list_weapon_types(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List the synthetic weapon type catalogue."""
    wts = db.query(WeaponType).order_by(WeaponType.code).all()
    return {"weapon_types": [_weapon_type_to_dict(w) for w in wts], "total": len(wts)}


@weapons_router.get("/inventory")
async def list_weapon_inventory(
    base_id: Optional[str] = None,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List weapon inventory, optionally filtered by base."""
    q = db.query(WeaponInventory)
    if base_id:
        q = q.filter(WeaponInventory.base_id == base_id)
    items = q.all()
    return {"inventory": [_inventory_to_dict(i) for i in items], "total": len(items)}


# ── Missions ──────────────────────────────────────────────────────────────────

@missions_router.get("")
async def list_missions(
    status_filter: Optional[str] = Query(None, alias="status"),
    priority: Optional[int] = None,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List synthetic missions, optionally filtered by status or priority."""
    q = db.query(Mission)
    if status_filter:
        try:
            q = q.filter(Mission.status == MissionStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    if priority is not None:
        q = q.filter(Mission.priority == priority)
    missions = q.order_by(Mission.priority, Mission.name).all()
    return {"missions": [_mission_to_dict(m) for m in missions], "total": len(missions)}


@missions_router.get("/{mission_id}")
async def get_mission(
    mission_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    mission = db.query(Mission).filter(Mission.id == mission_id).first()
    if not mission:
        raise HTTPException(status_code=404, detail="Mission not found")
    return _mission_to_dict(mission)


# ── Airspace & Threat Zones ───────────────────────────────────────────────────

@zones_router.get("/airspace")
async def list_airspace_zones(
    active_only: bool = False,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List synthetic airspace zones."""
    q = db.query(AirspaceZone)
    if active_only:
        q = q.filter(AirspaceZone.is_active == True)
    zones = q.all()
    return {"airspace_zones": [_airspace_to_dict(z) for z in zones], "total": len(zones)}


@zones_router.get("/threats")
async def list_threat_zones(
    active_only: bool = True,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List synthetic threat zones."""
    q = db.query(ThreatZone)
    if active_only:
        q = q.filter(ThreatZone.is_active == True)
    threats = q.order_by(ThreatZone.severity.desc()).all()
    return {"threat_zones": [_threat_to_dict(t) for t in threats], "total": len(threats)}


# ── Weather ───────────────────────────────────────────────────────────────────

@weather_router.get("")
async def list_weather(
    base_id: Optional[str] = None,
    go_only: bool = False,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List synthetic weather conditions."""
    q = db.query(WeatherCondition)
    if base_id:
        q = q.filter(WeatherCondition.base_id == base_id)
    if go_only:
        q = q.filter(WeatherCondition.is_go == True)
    conditions = q.order_by(WeatherCondition.recorded_at.desc()).all()
    return {
        "weather_conditions": [_weather_to_dict(w) for w in conditions],
        "total": len(conditions),
    }


# ── Data Feeds ────────────────────────────────────────────────────────────────

@feeds_router.get("")
async def list_feeds(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List all synthetic data feeds and their freshness/confidence status."""
    feeds = db.query(DataFeed).order_by(DataFeed.name).all()
    degraded_count = sum(1 for f in feeds if f.status != FeedStatus.LIVE)
    return {
        "feeds": [_feed_to_dict(f) for f in feeds],
        "total": len(feeds),
        "degraded_count": degraded_count,
        "all_live": degraded_count == 0,
    }

@feeds_router.post("/{feed_name}/ingest")
async def ingest_feed_data(
    feed_name: str,
    payload: dict,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db)
):
    """
    Ingest data from an external feed. Normalizes data and triggers events.
    """
    return ingest_feed(db, feed_name, payload, current_user.id)


@feeds_router.get("/fused-picture")
async def get_fused_picture(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db)
):
    """
    Return JDL Levels 1-3 Common Operational Data Picture with source confidence decay.
    """
    from backend.app.services.fusion import get_fused_tactical_picture
    return get_fused_tactical_picture(db)
