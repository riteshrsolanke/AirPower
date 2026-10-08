"""
Operational data seeder — Phase 1.
Populates: AirBase, Crew, WeaponType, WeaponInventory, AircraftWeaponCompat,
           Mission, AirspaceZone, ThreatZone, WeatherCondition,
           DataFeed, and updates Aircraft.mission_capable_status / base_id.
ALL DATA IS SYNTHETIC FOR DEMONSTRATION PURPOSES ONLY.
"""
import random
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.app.models.models import (
    AirBase, Crew, WeaponType, WeaponInventory, AircraftWeaponCompat,
    Mission, MissionStatus, AirspaceZone, ZoneType, ThreatZone, ThreatType,
    WeatherCondition, DataFeed, FeedStatus,
    Aircraft, AircraftMissionStatus,
    CrewDutyLog,
)

random.seed(99)   # separate seed so existing aircraft data doesn't change

# ── Synthetic base definitions ──────────────────────────────────────────────

BASES = [
    {
        "name": "Base Alpha",
        "icao_code": "DEMO",
        "latitude":  28.6139,   # synthetic coords near New Delhi area
        "longitude": 77.2090,
        "elevation_ft": 777,
        "runway_status": "OPERATIONAL",
        "max_aircraft_capacity": 20,
        "notes": "Primary synthetic forward operating base. All data simulated.",
    },
    {
        "name": "Base Bravo",
        "icao_code": "DEMB",
        "latitude":  19.0760,   # synthetic coords near Mumbai area
        "longitude": 72.8777,
        "elevation_ft": 37,
        "runway_status": "OPERATIONAL",
        "max_aircraft_capacity": 15,
        "notes": "Coastal synthetic operating base. All data simulated.",
    },
    {
        "name": "Base Charlie",
        "icao_code": "DEMC",
        "latitude":  13.0827,   # synthetic coords near Chennai area
        "longitude": 80.2707,
        "elevation_ft": 16,
        "runway_status": "DEGRADED",
        "max_aircraft_capacity": 12,
        "notes": "Southern synthetic operating base. Runway under repair (simulated).",
    },
    {
        "name": "Forward Station Delta",
        "icao_code": "DEMD",
        "latitude":  34.0837,   # synthetic coords near Jammu area
        "longitude": 74.7973,
        "elevation_ft": 5200,
        "runway_status": "OPERATIONAL",
        "max_aircraft_capacity": 8,
        "notes": "Synthetic forward operating location. All data simulated.",
    },
]

# ── Synthetic weapon types ──────────────────────────────────────────────────

WEAPON_TYPES = [
    {"code": "AAM-DEMO-SR",  "name": "Short-Range Air-to-Air Missile (Demo)", "category": "AAM",    "weight_kg": 90.0,   "range_km": 30.0},
    {"code": "AAM-DEMO-MR",  "name": "Medium-Range Air-to-Air Missile (Demo)","category": "AAM",    "weight_kg": 150.0,  "range_km": 100.0},
    {"code": "AGM-DEMO-AT",  "name": "Anti-Tank Guided Missile (Demo)",        "category": "AGM",    "weight_kg": 45.0,   "range_km": 8.0},
    {"code": "AGM-DEMO-AS",  "name": "Air-to-Surface Missile (Demo)",          "category": "AGM",    "weight_kg": 600.0,  "range_km": 250.0},
    {"code": "BOMB-DEMO-GP", "name": "General Purpose Bomb (Demo)",            "category": "BOMB",   "weight_kg": 500.0,  "range_km": 0.0},
    {"code": "BOMB-DEMO-LG", "name": "Laser Guided Bomb (Demo)",               "category": "BOMB",   "weight_kg": 500.0,  "range_km": 15.0},
    {"code": "TORP-DEMO-HW", "name": "Heavyweight Torpedo (Demo)",             "category": "TORPEDO","weight_kg": 1200.0, "range_km": 50.0},
    {"code": "POD-DEMO-REC", "name": "Reconnaissance Pod (Demo)",              "category": "POD",    "weight_kg": 300.0,  "range_km": 0.0},
]

# Map model prefix → compatible weapon codes
MODEL_WEAPON_MAP = {
    "DEMO-FIGHTER-Alpha":    ["AAM-DEMO-SR", "AAM-DEMO-MR", "AGM-DEMO-AS", "BOMB-DEMO-LG"],
    "DEMO-TRAINER-Bravo":    ["AAM-DEMO-SR", "POD-DEMO-REC"],
    "DEMO-TRANSPORT-Charlie":["POD-DEMO-REC"],
    "DEMO-HELICOPTER-Delta": ["AGM-DEMO-AT", "TORP-DEMO-HW"],
    "DEMO-MARITIME-Echo":    ["AGM-DEMO-AS", "TORP-DEMO-HW", "POD-DEMO-REC"],
}

# ── Synthetic crew definitions ──────────────────────────────────────────────

RANKS = ["Fg Offr", "Flt Lt", "Sqn Ldr", "Wg Cdr", "Gp Capt"]
ROLES = ["PILOT", "WSO", "NAVIGATOR", "LOADMASTER"]

CREW_QUAL_MAP = {
    "PILOT":      ["DEMO-FIGHTER-Alpha", "DEMO-TRAINER-Bravo"],
    "WSO":        ["DEMO-FIGHTER-Alpha"],
    "NAVIGATOR":  ["DEMO-TRANSPORT-Charlie", "DEMO-MARITIME-Echo"],
    "LOADMASTER": ["DEMO-TRANSPORT-Charlie", "DEMO-HELICOPTER-Delta"],
}

# ── Synthetic mission definitions ────────────────────────────────────────────

MISSION_TEMPLATES = [
    {
        "name": "MISSION-ALPHA-CAS",
        "mission_type": "CAS",
        "priority": 1,
        "estimated_duration_hours": 2.5,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code":   "AGM-DEMO-AS",
        "min_aircraft_count": 2,
        "target_area": {"lat": 29.5, "lon": 78.0, "radius_km": 20},
        "notes": "Synthetic close air support mission. Priority 1.",
    },
    {
        "name": "MISSION-BRAVO-DCA",
        "mission_type": "DCA",
        "priority": 1,
        "estimated_duration_hours": 3.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code":   "AAM-DEMO-MR",
        "min_aircraft_count": 2,
        "target_area": {"lat": 27.0, "lon": 76.5, "radius_km": 50},
        "notes": "Synthetic defensive counter-air patrol. Priority 1.",
    },
    {
        "name": "MISSION-CHARLIE-SEAD",
        "mission_type": "SEAD",
        "priority": 2,
        "estimated_duration_hours": 2.0,
        "required_aircraft_type": "DEMO-FIGHTER-Alpha",
        "required_weapon_code":   "AGM-DEMO-AS",
        "min_aircraft_count": 1,
        "target_area": {"lat": 31.0, "lon": 75.5, "radius_km": 15},
        "notes": "Synthetic suppression of enemy air defences. Priority 2.",
    },
    {
        "name": "MISSION-DELTA-ISR",
        "mission_type": "ISR",
        "priority": 2,
        "estimated_duration_hours": 4.0,
        "required_aircraft_type": "DEMO-MARITIME-Echo",
        "required_weapon_code":   "POD-DEMO-REC",
        "min_aircraft_count": 1,
        "target_area": {"lat": 15.0, "lon": 73.0, "radius_km": 80},
        "notes": "Synthetic intelligence, surveillance and reconnaissance. Priority 2.",
    },
    {
        "name": "MISSION-ECHO-TRANSPORT",
        "mission_type": "TRANSPORT",
        "priority": 3,
        "estimated_duration_hours": 5.0,
        "required_aircraft_type": "DEMO-TRANSPORT-Charlie",
        "required_weapon_code":   None,
        "min_aircraft_count": 1,
        "target_area": {"lat": 23.0, "lon": 72.0, "radius_km": 5},
        "notes": "Synthetic logistics transport. Priority 3.",
    },
    {
        "name": "MISSION-FOXTROT-SAR",
        "mission_type": "SAR",
        "priority": 2,
        "estimated_duration_hours": 3.0,
        "required_aircraft_type": "DEMO-HELICOPTER-Delta",
        "required_weapon_code":   None,
        "min_aircraft_count": 1,
        "target_area": {"lat": 33.5, "lon": 76.0, "radius_km": 30},
        "notes": "Synthetic search and rescue. Priority 2.",
    },
    {
        "name": "MISSION-GOLF-MARITIME",
        "mission_type": "ISR",
        "priority": 3,
        "estimated_duration_hours": 6.0,
        "required_aircraft_type": "DEMO-MARITIME-Echo",
        "required_weapon_code":   "TORP-DEMO-HW",
        "min_aircraft_count": 1,
        "target_area": {"lat": 12.0, "lon": 80.5, "radius_km": 100},
        "notes": "Synthetic maritime patrol. Priority 3.",
    },
    {
        "name": "MISSION-HOTEL-TRAINER",
        "mission_type": "CAS",
        "priority": 5,
        "estimated_duration_hours": 1.5,
        "required_aircraft_type": "DEMO-TRAINER-Bravo",
        "required_weapon_code":   "AAM-DEMO-SR",
        "min_aircraft_count": 1,
        "target_area": {"lat": 27.5, "lon": 77.0, "radius_km": 10},
        "notes": "Synthetic training sortie. Low priority.",
    },
]

# ── Data feed definitions ───────────────────────────────────────────────────

DATA_FEEDS = [
    {"name": "aircraft_health",   "description": "Synthetic aircraft sensor + ML prediction feed", "update_interval_seconds": 30,  "requires_signature": True},
    {"name": "crew_roster",       "description": "Synthetic crew duty-hour and availability feed", "update_interval_seconds": 300, "requires_signature": True},
    {"name": "weather_intel",     "description": "Synthetic meteorological data feed",              "update_interval_seconds": 600, "requires_signature": False},
    {"name": "threat_intel",      "description": "Synthetic threat-zone updates",                   "update_interval_seconds": 120, "requires_signature": True},
    {"name": "airspace_notam",    "description": "Synthetic NOTAM / airspace restriction feed",     "update_interval_seconds": 900, "requires_signature": False},
    {"name": "logistics_stock",   "description": "Synthetic weapon and spare parts inventory feed", "update_interval_seconds": 600, "requires_signature": True},
]


# ── Helper: compute mission-capable status ──────────────────────────────────

def compute_mission_capable(rul_hours: float, failure_risk: float) -> AircraftMissionStatus:
    """
    Derive mission-capable status from existing health metrics.
    Assumption (stated in plan):
      CAPABLE  : RUL >= 50 h AND failure_risk < 0.50
      LIMITED  : RUL 20-50 h OR failure_risk 0.50-0.75
      GROUNDED : RUL < 20 h  OR failure_risk > 0.75
    """
    if failure_risk > 0.75 or rul_hours < 20:
        return AircraftMissionStatus.GROUNDED
    if failure_risk > 0.50 or rul_hours < 50:
        return AircraftMissionStatus.LIMITED
    return AircraftMissionStatus.CAPABLE


# ── Public entry point ──────────────────────────────────────────────────────

def seed_operational_data(db: Session) -> None:
    """Idempotently seed all Phase-1 operational tables."""

    print("\n🗺️  Seeding operational data (Phase 1)...")

    bases   = _seed_bases(db)
    weapons = _seed_weapon_types(db)
    _seed_weapon_inventories(db, bases, weapons)
    _seed_crews(db, bases)
    _seed_weapon_compat(db, weapons)
    _seed_missions(db)
    _seed_airspace_zones(db)
    _seed_threat_zones(db)
    _seed_weather(db, bases)
    _seed_data_feeds(db)
    _update_aircraft_ops_fields(db, bases)

    print("  ✅ Operational seed complete.\n")


# ── Individual seeders ──────────────────────────────────────────────────────

def _seed_bases(db: Session):
    existing = {b.name for b in db.query(AirBase).all()}
    created = []
    for b in BASES:
        if b["name"] not in existing:
            obj = AirBase(**b)
            db.add(obj)
            created.append(b["name"])
    db.commit()
    all_bases = db.query(AirBase).all()
    if created:
        print(f"  → Created {len(created)} bases: {created}")
    else:
        print(f"  → Bases already exist ({len(all_bases)} total)")
    return {b.name: b for b in all_bases}


def _seed_weapon_types(db: Session):
    existing = {w.code for w in db.query(WeaponType).all()}
    for wt in WEAPON_TYPES:
        if wt["code"] not in existing:
            db.add(WeaponType(notes="Synthetic demonstration weapon.", **wt))
    db.commit()
    all_wt = db.query(WeaponType).all()
    print(f"  → {len(all_wt)} weapon types in catalogue")
    return {w.code: w for w in all_wt}


def _seed_weapon_inventories(db: Session, bases: dict, weapons: dict):
    count = 0
    for base_obj in bases.values():
        for code, wt in weapons.items():
            exists = db.query(WeaponInventory).filter_by(
                base_id=base_obj.id, weapon_type_id=wt.id
            ).first()
            if not exists:
                qty = random.randint(4, 24)
                db.add(WeaponInventory(
                    base_id=base_obj.id,
                    weapon_type_id=wt.id,
                    quantity=qty,
                    reserved_quantity=0,
                ))
                count += 1
    db.commit()
    print(f"  → Created {count} weapon inventory records")


def _seed_crews(db: Session, bases: dict):
    existing_count = db.query(Crew).count()
    if existing_count >= 30:
        print(f"  → Crews already exist ({existing_count} total)")
        return

    base_list = list(bases.values())
    names = [
        "Wg Cdr Arjun Sharma", "Sqn Ldr Priya Mehta", "Flt Lt Rohan Gupta",
        "Flt Lt Aisha Patel",  "Fg Offr Vikram Singh", "Sqn Ldr Nisha Rao",
        "Wg Cdr Deepak Kumar", "Flt Lt Sunita Joshi",  "Fg Offr Raj Verma",
        "Sqn Ldr Anita Desai", "Flt Lt Mohan Iyer",    "Fg Offr Kavya Nair",
        "Gp Capt Suresh Bose", "Sqn Ldr Rekha Pillai", "Flt Lt Amit Shah",
        "Fg Offr Divya Rao",   "Flt Lt Kiran Khanna",  "Sqn Ldr Neha Jain",
        "Wg Cdr Rajiv Menon",  "Flt Lt Pooja Chandra", "Fg Offr Arun Kumar",
        "Sqn Ldr Smita Reddy", "Flt Lt Manoj Sharma",  "Fg Offr Lakshmi Das",
        "Sqn Ldr Vivek Nair",  "Flt Lt Sonia Kapoor",  "Fg Offr Raj Malhotra",
        "Sqn Ldr Tara Singh",  "Flt Lt Alok Mathur",   "Fg Offr Priti Sinha",
    ]
    roles = (["PILOT"] * 16 + ["WSO"] * 6 + ["NAVIGATOR"] * 5 + ["LOADMASTER"] * 3)
    random.shuffle(roles)

    for i, (name, role) in enumerate(zip(names, roles)):
        base_obj = base_list[i % len(base_list)]
        duty = round(random.uniform(0, 10), 1)
        rest_status = "MANDATORY_REST" if duty >= 10 else ("FATIGUED" if duty >= 8 else "RESTED")
        qualifications = CREW_QUAL_MAP.get(role, [])
        c = Crew(
            name=name,
            rank=random.choice(RANKS),
            role=role,
            aircraft_qualifications=qualifications,
            duty_hours_used=duty,
            max_duty_hours=12.0,
            rest_status=rest_status,
            is_available=(rest_status != "MANDATORY_REST"),
            base_id=base_obj.id,
            notes="Synthetic aircrew record for demonstration.",
        )
        db.add(c)
        db.flush()
        
        # Add duty logs
        now = datetime.utcnow()
        # Some random past duty
        num_logs = random.randint(1, 5)
        for j in range(num_logs):
            end_t = now - timedelta(hours=random.randint(1, 48))
            start_t = end_t - timedelta(hours=random.randint(2, 6))
            night = random.choice([True, False])
            db.add(CrewDutyLog(crew_id=c.id, start_time=start_t, end_time=end_t, night_flag=night))

    db.commit()
    print(f"  → Created 30 synthetic crew members")


def _seed_weapon_compat(db: Session, weapons: dict):
    """Link each aircraft to compatible weapon types based on model."""
    aircraft_list = db.query(Aircraft).all()
    count = 0
    for ac in aircraft_list:
        compat_codes = MODEL_WEAPON_MAP.get(ac.model, [])
        for code in compat_codes:
            wt = weapons.get(code)
            if not wt:
                continue
            exists = db.query(AircraftWeaponCompat).filter_by(
                aircraft_id=ac.id, weapon_type_id=wt.id
            ).first()
            if not exists:
                db.add(AircraftWeaponCompat(
                    aircraft_id=ac.id,
                    weapon_type_id=wt.id,
                    max_load=2,
                ))
                count += 1
    db.commit()
    print(f"  → Created {count} aircraft-weapon compatibility records")


def _seed_missions(db: Session):
    existing = {m.name for m in db.query(Mission).all()}
    now = datetime.utcnow()
    count = 0
    for tmpl in MISSION_TEMPLATES:
        if tmpl["name"] in existing:
            continue
        window_start = now + timedelta(hours=random.randint(1, 6))
        window_end   = window_start + timedelta(hours=tmpl["estimated_duration_hours"] + 1)
        db.add(Mission(
            name=tmpl["name"],
            mission_type=tmpl["mission_type"],
            priority=tmpl["priority"],
            status=MissionStatus.PENDING,
            target_area=tmpl["target_area"],
            time_window_start=window_start,
            time_window_end=window_end,
            estimated_duration_hours=tmpl["estimated_duration_hours"],
            required_aircraft_type=tmpl.get("required_aircraft_type"),
            required_weapon_code=tmpl.get("required_weapon_code"),
            min_aircraft_count=tmpl["min_aircraft_count"],
            notes=tmpl["notes"],
        ))
        count += 1
    db.commit()
    print(f"  → Created {count} synthetic missions")


def _seed_airspace_zones(db: Session):
    existing = db.query(AirspaceZone).count()
    if existing:
        print(f"  → Airspace zones already exist ({existing} total)")
        return
    now = datetime.utcnow()
    zones = [
        {
            "name": "RESTRICTED-NORTH-1",
            "zone_type": ZoneType.RESTRICTED,
            "geometry": {"type": "circle", "center": [32.0, 76.0], "radius_km": 50},
            "floor_ft": 0, "ceiling_ft": 60000,
            "active_from": now, "active_until": now + timedelta(days=30),
            "is_active": True,
            "notes": "Synthetic restricted zone. Data simulated.",
        },
        {
            "name": "CORRIDOR-ALPHA",
            "zone_type": ZoneType.CORRIDOR,
            "geometry": {"type": "polygon", "coordinates": [
                [26.0, 75.0], [28.0, 75.0], [28.0, 78.0], [26.0, 78.0]
            ]},
            "floor_ft": 5000, "ceiling_ft": 25000,
            "active_from": now, "active_until": now + timedelta(days=30),
            "is_active": True,
            "notes": "Synthetic approved routing corridor.",
        },
        {
            "name": "DANGER-ZONE-WEST",
            "zone_type": ZoneType.DANGER,
            "geometry": {"type": "circle", "center": [28.0, 70.0], "radius_km": 80},
            "floor_ft": 0, "ceiling_ft": 40000,
            "active_from": now, "active_until": now + timedelta(hours=48),
            "is_active": True,
            "notes": "Synthetic danger zone – active for 48h.",
        },
        {
            "name": "RESTRICTED-SOUTH-1",
            "zone_type": ZoneType.RESTRICTED,
            "geometry": {"type": "circle", "center": [11.0, 79.0], "radius_km": 40},
            "floor_ft": 0, "ceiling_ft": 60000,
            "active_from": None, "active_until": None,
            "is_active": False,
            "notes": "Synthetic inactive restricted zone.",
        },
    ]
    for z in zones:
        db.add(AirspaceZone(**z))
    db.commit()
    print(f"  → Created {len(zones)} airspace zones")


def _seed_threat_zones(db: Session):
    existing = db.query(ThreatZone).count()
    if existing:
        print(f"  → Threat zones already exist ({existing} total)")
        return
    threats = [
        {"name": "SAM-SITE-NORTH-1",  "threat_type": ThreatType.SAM,    "center_lat": 33.0, "center_lon": 75.0, "radius_km": 30, "severity": 4, "is_active": True,  "notes": "Synthetic SAM envelope."},
        {"name": "AAA-CLUSTER-WEST",   "threat_type": ThreatType.AAA,    "center_lat": 28.5, "center_lon": 71.0, "radius_km": 15, "severity": 3, "is_active": True,  "notes": "Synthetic AAA cluster."},
        {"name": "FIGHTER-CAP-ALPHA",  "threat_type": ThreatType.FIGHTER,"center_lat": 30.0, "center_lon": 74.0, "radius_km": 60, "severity": 5, "is_active": True,  "notes": "Synthetic hostile fighter CAP area."},
        {"name": "EW-RADAR-SOUTH",     "threat_type": ThreatType.RADAR,  "center_lat": 14.0, "center_lon": 77.5, "radius_km": 200,"severity": 2, "is_active": True,  "notes": "Synthetic early-warning radar."},
        {"name": "SAM-SITE-EAST",      "threat_type": ThreatType.SAM,    "center_lat": 26.0, "center_lon": 88.0, "radius_km": 35, "severity": 3, "is_active": False, "notes": "Synthetic SAM site (inactive)."},
    ]
    for t in threats:
        db.add(ThreatZone(**t))
    db.commit()
    print(f"  → Created {len(threats)} threat zones")


def _seed_weather(db: Session, bases: dict):
    existing = db.query(WeatherCondition).count()
    if existing >= len(bases):
        print(f"  → Weather conditions already exist ({existing} total)")
        return
    base_weather = [
        {"visibility_km": 15.0, "wind_speed_kts": 8,  "wind_direction_deg": 270, "ceiling_ft": 8000,  "is_go": True},
        {"visibility_km": 12.0, "wind_speed_kts": 15, "wind_direction_deg": 220, "ceiling_ft": 5000,  "is_go": True},
        {"visibility_km": 4.0,  "wind_speed_kts": 25, "wind_direction_deg": 180, "ceiling_ft": 1500,  "is_go": False, "go_no_go_reason": "Low ceiling and visibility below minimums"},
        {"visibility_km": 8.0,  "wind_speed_kts": 20, "wind_direction_deg": 310, "ceiling_ft": 3000,  "is_go": True},
    ]
    base_list = list(bases.values())
    for i, base_obj in enumerate(base_list):
        wx = base_weather[i % len(base_weather)]
        db.add(WeatherCondition(
            base_id=base_obj.id,
            area_label=base_obj.name,
            visibility_km=wx["visibility_km"],
            wind_speed_kts=wx["wind_speed_kts"],
            wind_direction_deg=wx["wind_direction_deg"],
            ceiling_ft=wx["ceiling_ft"],
            temperature_c=round(random.uniform(15, 35), 1),
            is_go=wx["is_go"],
            go_no_go_reason=wx.get("go_no_go_reason"),
            confidence=round(random.uniform(0.75, 1.0), 2),
        ))
    # Also add weather for target areas
    target_areas = [
        ("NORTH-SECTOR",  32.0, 76.0, True,  None,                      10.0, 270),
        ("COASTAL-ZONE",  15.0, 73.5, True,  None,                      20.0, 180),
        ("WEST-SECTOR",   28.0, 70.0, False, "Thunderstorm activity",    3.0,  230),
    ]
    for (label, lat, lon, is_go, reason, vis, wind_dir) in target_areas:
        db.add(WeatherCondition(
            base_id=None,
            area_label=label,
            visibility_km=vis,
            wind_speed_kts=random.uniform(5, 30),
            wind_direction_deg=wind_dir,
            ceiling_ft=random.randint(2000, 15000),
            temperature_c=round(random.uniform(10, 40), 1),
            is_go=is_go,
            go_no_go_reason=reason,
            confidence=round(random.uniform(0.6, 0.95), 2),
        ))
    db.commit()
    print(f"  → Created weather conditions for {len(base_list)} bases + 3 target areas")


def _seed_data_feeds(db: Session):
    existing = {f.name for f in db.query(DataFeed).all()}
    count = 0
    for feed in DATA_FEEDS:
        if feed["name"] not in existing:
            db.add(DataFeed(
                name=feed["name"],
                description=feed["description"],
                update_interval_seconds=feed["update_interval_seconds"],
                last_update=datetime.utcnow(),
                status=FeedStatus.LIVE,
                confidence=1.0,
                requires_signature=feed["requires_signature"],
                notes="Synthetic data feed for fusion layer demonstration.",
            ))
            count += 1
    db.commit()
    print(f"  → Created {count} data feeds")


def _update_aircraft_ops_fields(db: Session, bases: dict):
    """
    Backfill mission_capable_status and base_id for all existing aircraft.
    Uses the location string to match a base name.
    """
    base_by_name = {name: obj.id for name, obj in bases.items()}
    aircraft_list = db.query(Aircraft).all()
    updated = 0
    for ac in aircraft_list:
        # Derive mission-capable status
        new_status = compute_mission_capable(ac.rul_hours, ac.failure_risk)
        changed = False
        if ac.mission_capable_status != new_status:
            ac.mission_capable_status = new_status
            changed = True
        # Link to base by location string
        base_id = base_by_name.get(ac.location)
        if base_id and ac.base_id != base_id:
            ac.base_id = base_id
            changed = True
        if changed:
            updated += 1
    db.commit()
    capable   = sum(1 for a in aircraft_list if a.mission_capable_status == AircraftMissionStatus.CAPABLE)
    limited   = sum(1 for a in aircraft_list if a.mission_capable_status == AircraftMissionStatus.LIMITED)
    grounded  = sum(1 for a in aircraft_list if a.mission_capable_status == AircraftMissionStatus.GROUNDED)
    print(f"  → Updated {updated} aircraft: CAPABLE={capable} LIMITED={limited} GROUNDED={grounded}")
