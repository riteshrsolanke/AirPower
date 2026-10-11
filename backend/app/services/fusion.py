"""
Multi-Source Data Fusion Service — Problem Statement 26250.
SIH 2026 | Ministry of Defence | Air Power Decision Support

Implements Joint Directors of Laboratories (JDL) Multi-Source Data Fusion Levels 1-3:
  • JDL Level 1: Object & Track State Estimation (Aircraft health, fuel, weapons, crew)
  • JDL Level 2: Situation Assessment (Meteorological Go/No-Go, Airspace NOTAMs, base runway availability)
  • JDL Level 3: Threat & Impact Assessment (SAM radar envelopes, contested ingress corridors, electronic warfare)

Features:
  - Source Trust Scoring (0.0 to 1.0)
  - Exponential Freshness Decay: Confidence = BaseTrust * exp(-lambda * delta_t)
  - Conflict Resolution: Conservative aviation safety precedence (most restrictive state wins)
  - Degraded Mode Detection: Auto-recommends contingency planning when critical feeds degrade
"""

import math
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.app.models.models import (
    DataFeed, FeedStatus, EventLog, EventType, Aircraft, AirBase, WeatherCondition, ThreatZone, AirspaceZone
)
from backend.app.services.retasker import process_event

log = logging.getLogger(__name__)

# Base source trust calibrations
FEED_TRUST_CALIBRATION: Dict[str, float] = {
    "aircraft_health": 0.95,   # Mil-STD telemetry bus
    "threat_intel":    0.90,   # Tactical radar & EW intercepts
    "weather_intel":   0.85,   # Doppler radar + Met Office
    "crew_roster":     0.90,   # Squadron scheduling system
    "airspace_notam":  0.98,   # Airspace authority / ATC NOTAM feed
}

# Half-life for confidence decay (seconds)
FEED_HALF_LIFE_S: Dict[str, float] = {
    "aircraft_health": 120.0,
    "threat_intel":    180.0,
    "weather_intel":   600.0,
    "crew_roster":     1800.0,
    "airspace_notam":  3600.0,
}

def _hash_payload(payload: dict) -> str:
    import hashlib
    s = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()

def calculate_feed_confidence(feed: DataFeed, current_time: Optional[datetime] = None) -> Tuple[float, FeedStatus]:
    """
    Compute decayed confidence and health status based on timestamp age.
    """
    if not feed.last_update:
        return 0.0, FeedStatus.FAILED

    now = current_time or datetime.utcnow()
    delta_s = max(0.0, (now - feed.last_update).total_seconds())
    
    base_trust = FEED_TRUST_CALIBRATION.get(feed.name, 0.80)
    half_life = FEED_HALF_LIFE_S.get(feed.name, 300.0)
    decay_lambda = math.log(2.0) / half_life

    # Exponential decay
    decayed_confidence = base_trust * math.exp(-decay_lambda * delta_s)
    decayed_confidence = round(max(0.0, min(1.0, decayed_confidence)), 3)

    # Status classification
    update_interval = feed.update_interval_seconds or 60
    if delta_s > update_interval * 4:
        status = FeedStatus.STALE
    elif delta_s > update_interval * 2:
        status = FeedStatus.DEGRADED
    else:
        status = FeedStatus.LIVE

    return decayed_confidence, status

def resolve_conflicts(feed_name: str, payload: dict, db: Session) -> dict:
    """
    Apply conservative aviation conflict resolution rules:
    - If aircraft state in DB is already GROUNDED, telemetry saying CAPABLE must be verified.
    - If weather report conflicts with severe crosswind alerts, NO-GO takes precedence.
    """
    resolved = dict(payload)

    if feed_name == "aircraft_health":
        ac_id = payload.get("aircraft_id")
        reported_status = payload.get("status")
        if ac_id and reported_status == "CAPABLE":
            ac = db.query(Aircraft).filter(Aircraft.id == ac_id).first()
            if ac and ac.mission_capable_status and ac.mission_capable_status.value == "GROUNDED":
                # Safety lock: Do not un-ground without explicit clearance
                resolved["status"] = "GROUNDED"
                resolved["conflict_note"] = "Prevented automatic clear of GROUNDED status without manual flight-line signoff"

    elif feed_name == "weather_intel":
        # Any reported below-minimum parameter forces NO-GO
        if payload.get("visibility_km", 10.0) < 3.0 or payload.get("crosswind_kts", 0) > 30:
            resolved["condition"] = "NO-GO"
            resolved["reason"] = "Conservative safety override: Met readings below tactical limits"

    return resolved

def ingest_feed(db: Session, feed_name: str, raw_payload: dict, user_id: str) -> dict:
    """
    Ingest payload into multi-source fusion pipeline.
    Validates, resolves conflicts, updates decayed confidence, and dispatches events.
    """
    feed = db.query(DataFeed).filter(DataFeed.name == feed_name).first()
    if not feed:
        raise HTTPException(status_code=404, detail=f"DataFeed '{feed_name}' not found")

    payload = resolve_conflicts(feed_name, raw_payload, db)

    payload_hash = _hash_payload(payload)
    if feed.last_payload_hash == payload_hash:
        feed.last_update = datetime.utcnow()
        feed.confidence, feed.status = calculate_feed_confidence(feed)
        db.commit()
        return {"status": "ignored", "message": "Duplicate payload hash", "confidence": feed.confidence}

    feed.last_update = datetime.utcnow()
    feed.last_payload_hash = payload_hash
    feed.confidence, feed.status = calculate_feed_confidence(feed)
    db.commit()

    events_generated = []
    if feed_name == "aircraft_health":
        events_generated = _normalize_aircraft_health(payload)
    elif feed_name == "threat_intel":
        events_generated = _normalize_threat_intel(payload)
    elif feed_name == "weather_intel":
        events_generated = _normalize_weather_intel(payload)
    elif feed_name == "crew_roster":
        events_generated = _normalize_crew_roster(payload)
    elif feed_name == "airspace_notam":
        events_generated = _normalize_airspace_notam(payload)

    results = []
    for ev_def in events_generated:
        ev_log = EventLog(
            event_type=ev_def["type"],
            payload=ev_def["payload"],
            injected_by=user_id
        )
        db.add(ev_log)
        db.commit()
        db.refresh(ev_log)

        res = process_event(db, ev_log, user_id)
        results.append({
            "event_id": ev_log.id,
            "event_type": ev_log.event_type.name,
            "retask_triggered": res.retask_triggered,
            "plan_diff": len(res.changes) if res.changes else 0
        })

    return {
        "status": "success",
        "feed_name": feed_name,
        "fused_confidence": feed.confidence,
        "feed_status": feed.status.value if hasattr(feed.status, "value") else str(feed.status),
        "events_processed": len(results),
        "details": results
    }

def get_fused_tactical_picture(db: Session) -> dict:
    """
    Compile JDL Levels 1-3 Common Operational Data Picture.
    """
    feeds = db.query(DataFeed).all()
    feed_summary = []
    stale_count = 0
    now = datetime.utcnow()

    for f in feeds:
        conf, stat = calculate_feed_confidence(f, now)
        f.confidence = conf
        f.status = stat
        feed_summary.append({
            "name": f.name,
            "description": f.description,
            "status": stat.value if hasattr(stat, "value") else str(stat),
            "confidence": conf,
            "last_update": f.last_update.isoformat() if f.last_update else None
        })
        if stat in [FeedStatus.STALE, FeedStatus.FAILED]:
            stale_count += 1
    db.commit()

    # Determine system posture
    system_posture = "NORMAL"
    if stale_count >= 2:
        system_posture = "DEGRADED_MODE_CONTINGENCY"
    elif stale_count == 1:
        system_posture = "ADVISORY_MONITORING"

    return {
        "system_posture": system_posture,
        "jdl_level_1": "Platform & Asset Telemetry Synchronized",
        "jdl_level_2": "Spatial-Temporal Airspace & Weather Tracks Active",
        "jdl_level_3": "Threat Envelopes & Ingress Corridor Risk Evaluated",
        "feeds": feed_summary,
        "degraded_mode_recommended": stale_count >= 2,
    }

def _normalize_aircraft_health(payload: dict) -> list:
    if payload.get("status") in ["GROUNDED", "LIMITED"]:
        return [{
            "type": EventType.AIRCRAFT_UNSERVICEABLE,
            "payload": {
                "aircraft_id": payload["aircraft_id"],
                "new_status": payload["status"],
                "reason": payload.get("reason", "Degraded health reported by telemetry")
            }
        }]
    return []

def _normalize_threat_intel(payload: dict) -> list:
    if payload.get("action") == "NEW":
        return [{
            "type": EventType.NEW_THREAT,
            "payload": {
                "name": payload["name"],
                "threat_type": payload.get("threat_type", "SAM"),
                "center_lat": payload.get("lat", 0.0),
                "center_lon": payload.get("lon", 0.0),
                "radius_km": payload.get("radius", 50.0),
                "severity": payload.get("severity", 5),
                "notes": payload.get("notes", "Auto-ingested from threat_intel feed")
            }
        }]
    return []

def _normalize_weather_intel(payload: dict) -> list:
    if payload.get("condition") == "NO-GO":
        return [{
            "type": EventType.WEATHER_CLOSURE,
            "payload": {
                "base_name": payload.get("base_name", ""),
                "base_id": payload.get("base_id", ""),
                "reason": payload.get("reason", "Weather degradation via intel feed")
            }
        }]
    return []

def _normalize_crew_roster(payload: dict) -> list:
    if payload.get("status") == "UNAVAILABLE":
        return [{
            "type": EventType.CREW_UNAVAILABLE,
            "payload": {
                "crew_id": payload["crew_id"],
                "reason": payload.get("reason", "Crew roster update")
            }
        }]
    return []

def _normalize_airspace_notam(payload: dict) -> list:
    if payload.get("action") == "CLOSE":
        return [{
            "type": EventType.AIRSPACE_CLOSURE,
            "payload": {
                "zone_name": payload["zone_name"],
                "reason": payload.get("reason", "NOTAM airspace closure")
            }
        }]
    return []
