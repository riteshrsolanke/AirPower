"""
Data Fusion Service — Phase 5.
Problem Statement 26250 | SIH 2026 | Ministry of Defence
ALL DATA IS SYNTHETIC — Not connected to operational defence systems.

Ingests simulated data feeds (weather, threats, aircraft telemetry),
normalizes them, and injects actionable events into the Retasker.
"""

from datetime import datetime
import json
import logging
from sqlalchemy.orm import Session
from fastapi import HTTPException

from backend.app.models.models import (
    DataFeed, FeedStatus, EventLog, EventType
)
from backend.app.services.retasker import process_event

log = logging.getLogger(__name__)

def _hash_payload(payload: dict) -> str:
    import hashlib
    s = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(s.encode()).hexdigest()

def ingest_feed(db: Session, feed_name: str, payload: dict, user_id: str) -> dict:
    """
    Ingest a raw JSON payload from an external feed.
    Validates, normalizes into internal events, and triggers retasking if needed.
    """
    feed = db.query(DataFeed).filter(DataFeed.name == feed_name).first()
    if not feed:
        raise HTTPException(status_code=404, detail=f"DataFeed '{feed_name}' not found")

    # Check for duplicates to prevent unnecessary replanning cycles
    payload_hash = _hash_payload(payload)
    if feed.last_payload_hash == payload_hash:
        # Same exact payload as last time, ignore it
        feed.last_update = datetime.utcnow()
        feed.status = FeedStatus.LIVE
        db.commit()
        return {"status": "ignored", "message": "Duplicate payload hash"}

    feed.last_update = datetime.utcnow()
    feed.status = FeedStatus.LIVE
    feed.last_payload_hash = payload_hash
    db.commit()

    events_generated = []
    
    # ── Dispatch to specialized normalizers ───────────────────────────────────
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
    # log / ignore others

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
        
        # Pass to Phase 3 retasker engine
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
        "events_processed": len(results),
        "details": results
    }

# ── Normalizers ───────────────────────────────────────────────────────────────

def _normalize_aircraft_health(payload: dict) -> list:
    """
    Expected: {"aircraft_id": "DEMO-A001", "health_score": 45, "status": "GROUNDED", "reason": "..."}
    """
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
    """
    Expected: {"action": "NEW", "name": "...", "threat_type": "SAM", "lat": 28, "lon": 77, "radius": 50, "severity": 5}
    """
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
    """
    Expected: {"base_name": "Base Alpha", "condition": "NO-GO", "reason": "Crosswinds"}
    """
    if payload.get("condition") == "NO-GO":
        return [{
            "type": EventType.WEATHER_CLOSURE,
            "payload": {
                "base_name": payload["base_name"],
                "reason": payload.get("reason", "Weather degradation via intel feed")
            }
        }]
    return []

def _normalize_crew_roster(payload: dict) -> list:
    """
    Expected: {"crew_id": "C-001", "status": "UNAVAILABLE", "reason": "Fatigue"}
    """
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
    """
    Expected: {"action": "CLOSE", "zone_name": "Restricted-X"}
    """
    if payload.get("action") == "CLOSE":
        return [{
            "type": EventType.AIRSPACE_CLOSURE,
            "payload": {
                "zone_name": payload["zone_name"],
                "reason": payload.get("reason", "NOTAM airspace closure")
            }
        }]
    return []
