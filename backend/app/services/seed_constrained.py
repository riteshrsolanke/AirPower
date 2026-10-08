"""
Constrained SIH Demonstration Scenario Seeder — Problem Statement 26250.
SIH 2026 | Ministry of Defence | Team $NEXORA$

SYNTHETIC DEMONSTRATION PROTOTYPE ONLY.
Not connected to operational defence systems.

This module seeds a deliberately constrained operational scenario where:
  - 10 competing missions contend for limited platform slots
  - High-priority missions conflict on required aircraft models
  - Clear trade-offs emerge between MAX_COVERAGE, MIN_RISK, and RESOURCE_LEAN
  - Real constraints (Range, Fuel, Payload, Base Capacity, Weather, Crew) dictate feasibility
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.app.models.models import (
    AirBase, Aircraft, AircraftMissionStatus, AircraftStatus,
    AircraftWeaponCompat, Crew, CrewDutyLog, Mission, MissionPlan,
    MissionStatus, PlanAssignment, PlanStatus, ThreatZone, ThreatType,
    WeaponInventory, WeaponType, WeatherCondition, User,
)

log = logging.getLogger(__name__)


CONSTRAINED_MISSIONS = [
    {
        "name": "SIH-M01-STRATEGIC-AIR-DEFENCE",
        "mission_type": "DCA",
        "priority": 1,
        "estimated_duration_hours": 3.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "AAM-DEMO-MR",
        "min_aircraft_count": 2,
        "distance_km": 600.0,
        "required_payload": 2000.0,
        "target_area": {"lat": 28.5, "lon": 76.8, "radius_km": 40},
        "notes": "Urgent DCA corridor defense. Requires 2 frontline air superiority fighters.",
    },
    {
        "name": "SIH-M02-SEAD-PENETRATION-STRIKE",
        "mission_type": "SEAD",
        "priority": 1,
        "estimated_duration_hours": 2.5,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "AGM-DEMO-AS",
        "min_aircraft_count": 1,
        "distance_km": 750.0,
        "required_payload": 2200.0,
        "target_area": {"lat": 32.5, "lon": 74.8, "radius_km": 25}, # Inside SAM-SITE-NORTH (severity 5)
        "notes": "Extreme-threat SEAD strike. High hostile radar coverage.",
    },
    {
        "name": "SIH-M03-FORWARD-CAS-SUPPORT",
        "mission_type": "CAS",
        "priority": 1,
        "estimated_duration_hours": 2.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "AGM-DEMO-AS",
        "min_aircraft_count": 2,
        "distance_km": 450.0,
        "required_payload": 1800.0,
        "target_area": {"lat": 30.1, "lon": 74.1, "radius_km": 30},
        "notes": "Immediate frontline CAS support request under contested CAP umbrella. Competes for fighter airframes.",
    },
    {
        "name": "SIH-M04-COASTAL-MARITIME-RECON",
        "mission_type": "ISR",
        "priority": 2,
        "estimated_duration_hours": 4.5,
        "required_aircraft_type": "DEMO-MARITIME-Echo",
        "required_weapon_code": "POD-DEMO-REC",
        "min_aircraft_count": 1,
        "distance_km": 1600.0,
        "required_payload": 900.0,
        "target_area": {"lat": 16.5, "lon": 72.8, "radius_km": 90},
        "notes": "Extended maritime surveillance patrol.",
    },
    {
        "name": "SIH-M05-STRATEGIC-AIRLIFT-SUPPLY",
        "mission_type": "TRANSPORT",
        "priority": 2,
        "estimated_duration_hours": 4.0,
        "required_aircraft_type": "DEMO-TRANSPORT-Charlie",
        "required_weapon_code": None,
        "min_aircraft_count": 1,
        "distance_km": 1400.0,
        "required_payload": 9500.0,
        "target_area": {"lat": 24.0, "lon": 73.0, "radius_km": 15},
        "notes": "Heavy logistics resupply sortie to forward airfield.",
    },
    {
        "name": "SIH-M06-MOUNTAIN-SAR-EXTRACTION",
        "mission_type": "SAR",
        "priority": 2,
        "estimated_duration_hours": 3.0,
        "required_aircraft_type": "DEMO-HELICOPTER-Delta",
        "required_weapon_code": None,
        "min_aircraft_count": 1,
        "distance_km": 320.0,
        "required_payload": 1100.0,
        "target_area": {"lat": 33.8, "lon": 75.2, "radius_km": 20},
        "notes": "High-altitude casualty evacuation sortie.",
    },
    {
        "name": "SIH-M07-SECONDARY-CAS-RESERVE",
        "mission_type": "CAS",
        "priority": 3,
        "estimated_duration_hours": 2.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "BOMB-DEMO-LG",
        "min_aircraft_count": 1,
        "distance_km": 500.0,
        "required_payload": 1800.0,
        "target_area": {"lat": 28.0, "lon": 77.5, "radius_km": 25},
        "notes": "Secondary ground interdiction sortie. Dropped under tight resource constraints.",
    },
    {
        "name": "SIH-M08-BORDER-AIR-SWEEP",
        "mission_type": "DCA",
        "priority": 3,
        "estimated_duration_hours": 3.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code": "AAM-DEMO-MR",
        "min_aircraft_count": 2,
        "distance_km": 700.0,
        "required_payload": 2000.0,
        "target_area": {"lat": 29.5, "lon": 74.5, "radius_km": 40},
        "notes": "Border combat air patrol. Resource-intensive (demands 2 fighters).",
    },
    {
        "name": "SIH-M09-ANTI-SUBMARINE-PATROL",
        "mission_type": "ISR",
        "priority": 4,
        "estimated_duration_hours": 5.5,
        "required_aircraft_type": "DEMO-MARITIME-Echo",
        "required_weapon_code": "TORP-DEMO-HW",
        "min_aircraft_count": 1,
        "distance_km": 2400.0,
        "required_payload": 2800.0,
        "target_area": {"lat": 13.0, "lon": 80.5, "radius_km": 120},
        "notes": "Extended ASW patrol. Competing with M04 for limited maritime airframe.",
    },
    {
        "name": "SIH-M10-TACTICAL-TRAINING-SORTIE",
        "mission_type": "CAS",
        "priority": 5,
        "estimated_duration_hours": 1.5,
        "required_aircraft_type": "DEMO-TRAINER-Bravo",
        "required_weapon_code": "AAM-DEMO-SR",
        "min_aircraft_count": 1,
        "distance_km": 220.0,
        "required_payload": 400.0,
        "target_area": {"lat": 27.2, "lon": 77.2, "radius_km": 15},
        "notes": "Low priority pilot proficiency sortie in non-contested airspace.",
    },
]


def seed_constrained_scenario(db: Session) -> Dict[str, Any]:
    """
    Apply the Constrained SIH Demo Scenario to the database.
    Demonstrates clear trade-offs across MAX_COVERAGE, MIN_RISK, and RESOURCE_LEAN.
    """
    log.info("Seeding constrained SIH demo scenario...")

    # 1. Update bases: set tight capacity constraints
    bases = db.query(AirBase).all()
    base_by_name = {b.name: b for b in bases}

    if "Base Alpha" in base_by_name:
        base_by_name["Base Alpha"].max_aircraft_capacity = 3
    if "Base Bravo" in base_by_name:
        base_by_name["Base Bravo"].max_aircraft_capacity = 3
    if "Base Charlie" in base_by_name:
        base_by_name["Base Charlie"].max_aircraft_capacity = 2
    if "Forward Station Delta" in base_by_name:
        base_by_name["Forward Station Delta"].max_aircraft_capacity = 2

    # 2. Update aircraft to introduce genuine scarcity
    # 4 capable fighters, 1 limited, rest grounded
    aircraft_list = db.query(Aircraft).all()

    fighter_count = 0
    transport_count = 0
    heli_count = 0
    maritime_count = 0
    trainer_count = 0

    base_alpha = base_by_name.get("Base Alpha")
    base_bravo = base_by_name.get("Base Bravo")
    base_delta = base_by_name.get("Forward Station Delta")

    for ac in aircraft_list:
        if ac.model == "DEMO-FIGHTER-Alpha":
            fighter_count += 1
            if fighter_count in [1, 2]:
                # 2 capable fighters at Base Alpha
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 94.0
                ac.rul_hours = 120.0
                ac.failure_risk = 0.10
                ac.base_id = base_alpha.id if base_alpha else ac.base_id
                ac.range_km = 1500.0
                ac.fuel_capacity = 4200.0
                ac.payload_capacity = 3500.0
            elif fighter_count in [3, 4]:
                # 2 capable fighters at Base Bravo
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 88.0
                ac.rul_hours = 95.0
                ac.failure_risk = 0.20
                ac.base_id = base_bravo.id if base_bravo else ac.base_id
                ac.range_km = 1500.0
                ac.fuel_capacity = 4200.0
                ac.payload_capacity = 3500.0
            elif fighter_count == 5:
                # 1 limited fighter (low RUL: 22h, insufficient for 3h mission + 20h margin)
                ac.mission_capable_status = AircraftMissionStatus.LIMITED
                ac.health_score = 65.0
                ac.rul_hours = 21.5
                ac.failure_risk = 0.55
                ac.base_id = base_alpha.id if base_alpha else ac.base_id
                ac.range_km = 1500.0
                ac.fuel_capacity = 4200.0
                ac.payload_capacity = 3500.0
            else:
                # All other fighters grounded (engine overhaul / hydraulic fault)
                ac.mission_capable_status = AircraftMissionStatus.GROUNDED
                ac.health_score = 40.0
                ac.rul_hours = 12.0
                ac.failure_risk = 0.85

        elif ac.model == "DEMO-TRANSPORT-Charlie":
            transport_count += 1
            if transport_count == 1:
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 90.0
                ac.rul_hours = 250.0
                ac.failure_risk = 0.12
                ac.base_id = base_bravo.id if base_bravo else ac.base_id
                ac.range_km = 3500.0
                ac.fuel_capacity = 15000.0
                ac.payload_capacity = 12000.0
            else:
                ac.mission_capable_status = AircraftMissionStatus.GROUNDED
                ac.health_score = 35.0
                ac.failure_risk = 0.88

        elif ac.model == "DEMO-HELICOPTER-Delta":
            heli_count += 1
            if heli_count == 1:
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 86.0
                ac.rul_hours = 80.0
                ac.failure_risk = 0.15
                ac.base_id = base_delta.id if base_delta else ac.base_id
                ac.range_km = 500.0
                ac.fuel_capacity = 1200.0
                ac.payload_capacity = 1500.0
            else:
                ac.mission_capable_status = AircraftMissionStatus.GROUNDED
                ac.failure_risk = 0.90

        elif ac.model == "DEMO-MARITIME-Echo":
            maritime_count += 1
            if maritime_count == 1:
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 91.0
                ac.rul_hours = 300.0
                ac.failure_risk = 0.14
                ac.base_id = base_bravo.id if base_bravo else ac.base_id
                ac.range_km = 4000.0
                ac.fuel_capacity = 18000.0
                ac.payload_capacity = 8000.0
            else:
                ac.mission_capable_status = AircraftMissionStatus.GROUNDED
                ac.failure_risk = 0.82

        elif ac.model == "DEMO-TRAINER-Bravo":
            trainer_count += 1
            if trainer_count == 1:
                ac.mission_capable_status = AircraftMissionStatus.CAPABLE
                ac.health_score = 89.0
                ac.rul_hours = 110.0
                ac.failure_risk = 0.16
                ac.base_id = base_alpha.id if base_alpha else ac.base_id
                ac.range_km = 800.0
                ac.fuel_capacity = 1500.0
                ac.payload_capacity = 800.0
            else:
                ac.mission_capable_status = AircraftMissionStatus.GROUNDED
                ac.failure_risk = 0.80

    # 3. Clear existing mission plans and assignments to enable a clean demonstration
    db.query(PlanAssignment).delete()
    db.query(MissionPlan).delete()

    # 4. Replace missions with the 10 constrained demonstration missions
    db.query(Mission).delete()
    now = datetime.utcnow()

    for tmpl in CONSTRAINED_MISSIONS:
        window_start = now + timedelta(hours=1)
        window_end = window_start + timedelta(hours=tmpl["estimated_duration_hours"] + 2)

        m_obj = Mission(
            name=tmpl["name"],
            mission_type=tmpl["mission_type"],
            priority=tmpl["priority"],
            status=MissionStatus.PENDING,
            target_area=tmpl["target_area"],
            time_window_start=window_start,
            time_window_end=window_end,
            estimated_duration_hours=tmpl["estimated_duration_hours"],
            required_aircraft_type=tmpl["required_aircraft_type"],
            required_weapon_code=tmpl["required_weapon_code"],
            min_aircraft_count=tmpl["min_aircraft_count"],
            distance_km=tmpl["distance_km"],
            required_payload=tmpl["required_payload"],
            notes=tmpl["notes"],
        )
        db.add(m_obj)

    # 5. Ensure high-threat zones are configured for visible MIN_RISK separation
    high_threat = db.query(ThreatZone).filter(ThreatZone.name == "SAM-SITE-NORTH-1").first()
    if high_threat:
        high_threat.center_lat = 32.5
        high_threat.center_lon = 74.8
        high_threat.radius_km = 60.0
        high_threat.severity = 5
        high_threat.is_active = True

    db.commit()

    # Generate the initial 3 plans immediately so they can be inspected right away
    analyst_user = db.query(User).filter(User.username == "analyst").first()
    creator_id = analyst_user.id if analyst_user else None
    from backend.app.services.optimizer import generate_plans
    plans = generate_plans(db, created_by_user_id=creator_id)

    plan_summaries = [
        {
            "plan_type": p.plan_type,
            "version": p.version,
            "coverage_pct": p.coverage_pct,
            "risk_score": p.risk_score,
            "aircraft_assigned": p.resource_use["aircraft_assigned"],
            "missions_covered": f"{p.resource_use['missions_covered']}/{p.resource_use['missions_total']}",
            "missions_dropped": p.resource_use["missions_dropped"],
            "solve_time_ms": p.solve_time_ms,
            "summary": p.summary,
        }
        for p in plans
    ]

    return {
        "status": "success",
        "scenario_name": "CONSTRAINED_SIH_DEMO_SCENARIO",
        "description": "10 competing missions contending for 4 capable fighter platforms with explicit risk & resource trade-offs.",
        "missions_count": len(CONSTRAINED_MISSIONS),
        "capable_fighters": 4,
        "plans_generated": plan_summaries,
    }


def reset_baseline_scenario(db: Session) -> Dict[str, Any]:
    """
    Restore the standard baseline demonstration scenario (8 missions, full fleet availability).
    """
    log.info("Resetting to standard baseline scenario...")
    from backend.app.services.seed_ops import BASES, MISSION_TEMPLATES, _seed_missions, _update_aircraft_ops_fields

    # Restore base capacities
    bases = db.query(AirBase).all()
    base_defaults = {b["name"]: b["max_aircraft_capacity"] for b in BASES}
    for b in bases:
        if b.name in base_defaults:
            b.max_aircraft_capacity = base_defaults[b.name]

    # Clear constrained plans and missions
    db.query(PlanAssignment).delete()
    db.query(MissionPlan).delete()
    db.query(Mission).delete()

    # Restore standard missions
    _seed_missions(db)

    # Re-evaluate aircraft capabilities from RUL and failure risk
    base_dict = {b.name: b for b in bases}
    _update_aircraft_ops_fields(db, base_dict)

    db.commit()

    # Generate fresh baseline plans
    analyst_user = db.query(User).filter(User.username == "analyst").first()
    creator_id = analyst_user.id if analyst_user else None
    from backend.app.services.optimizer import generate_plans
    plans = generate_plans(db, created_by_user_id=creator_id)

    return {
        "status": "success",
        "scenario_name": "STANDARD_BASELINE_SCENARIO",
        "description": "Standard baseline scenario restored (8 missions, unconstrained availability).",
        "missions_count": len(MISSION_TEMPLATES),
        "plans_generated": [
            {
                "plan_type": p.plan_type,
                "coverage_pct": p.coverage_pct,
                "risk_score": p.risk_score,
                "summary": p.summary,
            }
            for p in plans
        ],
    }
