"""
Tests for PS 26250 Implementation Gaps (Phases 1-13).
Validates all 10 core gap requirements defined in the audit baseline.
ALL DATA IS SYNTHETIC.
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
import pyotp

from backend.app.main import app
from backend.app.db.database import get_db
from backend.app.models.models import User, Aircraft, Crew, Mission, AirBase, MissionPlan
from backend.app.services.optimizer import (
    _check_aircraft_mission_feasibility,
    solve_operational_scenario,
    generate_plans,
)
from backend.app.services.whatif import run_operational_whatif

client = TestClient(app)


@pytest.fixture(scope="module")
def admin_credentials():
    return {"username": "admin", "password": "123"}


@pytest.fixture(scope="module")
def analyst_token():
    res = client.post("/api/auth/login", json={"username": "analyst", "password": "123"})
    return res.json()["access_token"]


@pytest.fixture(scope="module")
def viewer_token():
    res = client.post("/api/auth/login", json={"username": "viewer", "password": "123"})
    return res.json()["access_token"]


@pytest.fixture(scope="module")
def admin_token(admin_credentials):
    res = client.post("/api/auth/login", json=admin_credentials)
    data = res.json()
    if data.get("requires_mfa"):
        db = next(get_db())
        admin = db.query(User).filter(User.username == "admin").first()
        code = pyotp.TOTP(admin.mfa_secret).now()
        res_mfa = client.post("/api/auth/mfa/verify", json={"temp_token": data["temp_token"], "code": code})
        return res_mfa.json()["access_token"]
    return data["access_token"]


# ── TEST 1: Aircraft unavailable -> plan changes ──────────────────────────────
def test_gap_1_aircraft_unavailable_plan_changes(admin_token):
    db = next(get_db())
    admin_user = db.query(User).filter(User.username == "admin").first()

    # Find the latest plan and an assigned aircraft
    plan = db.query(MissionPlan).order_by(MissionPlan.created_at.desc()).first()
    if not plan or not plan.assignments:
        generate_plans(db, created_by_user_id=admin_user.id)
        plan = db.query(MissionPlan).order_by(MissionPlan.created_at.desc()).first()

    assigned_ac_id = plan.assignments[0].aircraft_id

    sim = run_operational_whatif(
        db=db,
        scenario_type="AIRCRAFT_UNAVAILABLE",
        entity_id=assigned_ac_id,
        base_plan_id=plan.id,
        parameters={"reason": "Simulated engine grounding"},
        objective="MAX_COVERAGE",
        current_user=admin_user,
    )

    assert sim["simulation_id"] is not None
    assert "plan_diff" in sim

    # The unavailable aircraft must not be assigned in the simulated plan
    sim_ac_ids = [a["aircraft_id"] for a in sim["simulated_plan"]["assignments"]]
    assert assigned_ac_id not in sim_ac_ids

    # Plan diff must record the change
    diff = sim["plan_diff"]
    assert any(c["prev_aircraft_id"] == assigned_ac_id for c in diff)


# ── TEST 2: Crew unavailable -> affected mission replanned ────────────────────
def test_gap_2_crew_unavailable_replanned(admin_token):
    db = next(get_db())
    admin_user = db.query(User).filter(User.username == "admin").first()

    plan = db.query(MissionPlan).order_by(MissionPlan.created_at.desc()).first()
    if not plan or not plan.assignments:
        generate_plans(db, created_by_user_id=admin_user.id)
        plan = db.query(MissionPlan).order_by(MissionPlan.created_at.desc()).first()

    assigned_crew_id = next((a.crew_id for a in plan.assignments if a.crew_id), None)
    assert assigned_crew_id is not None

    sim = run_operational_whatif(
        db=db,
        scenario_type="CREW_UNAVAILABLE",
        entity_id=assigned_crew_id,
        base_plan_id=plan.id,
        parameters={"reason": "Mandatory rest grounding"},
        objective="MAX_COVERAGE",
        current_user=admin_user,
    )

    assert sim["simulation_id"] is not None
    assert "plan_diff" in sim

    # Check that crew is no longer assigned to any mission in simulated plan
    for m in sim["simulated_plan"]["assignments"]:
        assert m.get("crew_id") != assigned_crew_id


# ── TEST 3: Time window impossible -> assignment rejected ─────────────────────
def test_gap_3_time_window_conflict_rejected():
    now = datetime.utcnow()
    m_conflict = Mission(
        id="M-WINDOW-FAIL",
        name="Urgent Intercept",
        mission_type="CAP",
        priority=1,
        time_window_start=now,
        time_window_end=now + timedelta(hours=1.0),
        estimated_duration_hours=3.5,  # 3.5 h duration > 1.0 h window!
        required_aircraft_type="DEMO-FIGHTER-Alpha",
        distance_km=200,
        required_payload=1000,
    )
    ac = Aircraft(
        id="AC-FEASIBLE",
        model="DEMO-FIGHTER-Alpha",
        serial_number="SN-FEAS-01",
        status="AVAILABLE",
        mission_capable_status="CAPABLE",
        range_km=1500,
        fuel_capacity=9000,
        payload_capacity=6000,
    )

    is_feasible, reasons = _check_aircraft_mission_feasibility(
        aircraft=ac,
        mission=m_conflict,
        weather_map={},
        weapon_inventory={},
        weapon_compat=set(),
    )
    assert is_feasible is False
    assert any("time window" in r.lower() for r in reasons)


# ── TEST 4: Range insufficient -> assignment rejected ─────────────────────────
def test_gap_4_range_insufficient_rejected():
    now = datetime.utcnow()
    m_long_range = Mission(
        id="M-DEEP-STRIKE",
        name="Deep Strike",
        mission_type="STRIKE",
        priority=1,
        time_window_start=now,
        time_window_end=now + timedelta(hours=6.0),
        estimated_duration_hours=2.0,
        required_aircraft_type="DEMO-FIGHTER-Alpha",
        distance_km=2500,  # 2500 km distance
        required_payload=1000,
    )
    ac_short_range = Aircraft(
        id="AC-SHORT-RANGE",
        model="DEMO-FIGHTER-Alpha",
        serial_number="SN-SHORT-01",
        status="AVAILABLE",
        mission_capable_status="CAPABLE",
        range_km=800,  # Only 800 km range!
        fuel_capacity=9000,
        payload_capacity=6000,
    )

    is_feasible, reasons = _check_aircraft_mission_feasibility(
        aircraft=ac_short_range,
        mission=m_long_range,
        weather_map={},
        weapon_inventory={},
        weapon_compat=set(),
    )
    assert is_feasible is False
    assert any("range constraint" in r.lower() for r in reasons)


# ── TEST 5: Base capacity exceeded -> assignment rejected ─────────────────────
def test_gap_5_base_capacity_enforced():
    base = AirBase(
        id="BASE-TINY",
        name="Tiny FOB",
        icao_code="VETN",
        latitude=28.0,
        longitude=77.0,
        max_aircraft_capacity=1,
    )
    ac1 = Aircraft(id="AC-B1", model="DEMO-FIGHTER-Alpha", serial_number="SN-B1", status="AVAILABLE", mission_capable_status="CAPABLE", base_id=base.id, range_km=1000, fuel_capacity=5000, payload_capacity=4000)
    ac2 = Aircraft(id="AC-B2", model="DEMO-FIGHTER-Alpha", serial_number="SN-B2", status="AVAILABLE", mission_capable_status="CAPABLE", base_id=base.id, range_km=1000, fuel_capacity=5000, payload_capacity=4000)
    now = datetime.utcnow()
    m1 = Mission(id="M-C1", name="Sortie 1", mission_type="CAP", priority=1, time_window_start=now, time_window_end=now+timedelta(hours=4), estimated_duration_hours=1.5, required_aircraft_type="DEMO-FIGHTER-Alpha", distance_km=200, required_payload=500)
    m2 = Mission(id="M-C2", name="Sortie 2", mission_type="CAP", priority=1, time_window_start=now, time_window_end=now+timedelta(hours=4), estimated_duration_hours=1.5, required_aircraft_type="DEMO-FIGHTER-Alpha", distance_km=200, required_payload=500)
    crew1 = Crew(id="CR-1", name="Capt A", rank="Flt Lt", role="PILOT_FIGHTER", is_available=True, rest_status="RESTED", duty_hours_used=0, max_duty_hours=12, base_id=base.id)
    crew2 = Crew(id="CR-2", name="Capt B", rank="Flt Lt", role="PILOT_FIGHTER", is_available=True, rest_status="RESTED", duty_hours_used=0, max_duty_hours=12, base_id=base.id)

    assignments, dropped, cov, risk, res_use, ms, summary = solve_operational_scenario(
        missions=[m1, m2],
        aircraft=[ac1, ac2],
        crews=[crew1, crew2],
        threats=[],
        weather_map={},
        weapon_inventory={},
        weapon_compat=set(),
        wt_by_code={},
        base_capacities={base.id: 1},
        base_names={base.id: base.name},
        plan_type="MAX_COVERAGE",
    )
    assigned_from_base = [a for a in assignments if a.aircraft_id in ["AC-B1", "AC-B2"]]
    assert len(assigned_from_base) <= base.max_aircraft_capacity


# ── TEST 6: What-If simulation -> database production state unchanged ─────────
def test_gap_6_whatif_zero_database_mutation(admin_token):
    db = next(get_db())

    # Record snapshot of production database
    aircraft_count_before = db.query(Aircraft).count()
    mission_count_before = db.query(Mission).count()
    crew_count_before = db.query(Crew).count()
    target_ac = db.query(Aircraft).first()
    initial_status = target_ac.mission_capable_status

    # Run What-If simulation making this aircraft unavailable
    res = client.post(
        "/api/planning/whatif",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "scenario_type": "AIRCRAFT_UNAVAILABLE",
            "entity_id": target_ac.id,
            "objective": "MAX_COVERAGE",
            "parameters": {"reason": "Synthetic simulation test"}
        }
    )
    assert res.status_code == 200

    # Verify database state was NOT changed
    db.expire_all()
    assert db.query(Aircraft).count() == aircraft_count_before
    assert db.query(Mission).count() == mission_count_before
    assert db.query(Crew).count() == crew_count_before
    refreshed_ac = db.query(Aircraft).filter(Aircraft.id == target_ac.id).first()
    assert refreshed_ac.mission_capable_status == initial_status


# ── TEST 7: What-If -> before/after plan diff generated ────────────────────────
def test_gap_7_whatif_diff_generation(analyst_token):
    res = client.post(
        "/api/planning/whatif",
        headers={"Authorization": f"Bearer {analyst_token}"},
        json={
            "scenario_type": "AIRCRAFT_UNAVAILABLE",
            "entity_id": "DEMO-A001",
            "objective": "MAX_COVERAGE",
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "current_plan" in data or "base_plan" in data
    assert "simulated_plan" in data
    assert "plan_diff" in data
    assert isinstance(data["plan_diff"], list)
    for change in data["plan_diff"]:
        assert change["change_type"] in ["ADDED", "REMOVED", "REPLACED", "RETAINED"]
        assert "mission_id" in change
        assert "note" in change


# ── TEST 8: Hardcoded crew count removed -> real API metrics returned ─────────
def test_gap_8_crew_readiness_metrics(analyst_token):
    res = client.get("/api/crews/summary/readiness", headers={"Authorization": f"Bearer {analyst_token}"})
    assert res.status_code == 200
    data = res.json()

    # Check required dynamic keys
    assert "total" in data
    assert "available" in data
    assert "fit" in data
    assert "caution" in data
    assert "unfit" in data

    # Logical consistency
    assert isinstance(data["total"], int)
    assert isinstance(data["available"], int)
    assert data["total"] > 0
    assert data["available"] <= data["total"]
    assert data["available"] == data["fit"] + data["caution"]
    assert data["total"] == data["available"] + data["unfit"]


# ── TEST 9: Unauthorized user -> planning endpoint rejected ───────────────────
def test_gap_9_unauthorized_user_rejected(viewer_token):
    # Unauthenticated attempt -> 401
    res_unauth = client.post("/api/planning/generate", json={})
    assert res_unauth.status_code == 401

    # Viewer role (read-only) attempting planning generate -> 403 Forbidden
    res_viewer = client.post(
        "/api/planning/generate",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={}
    )
    assert res_viewer.status_code == 403

    # Viewer role attempting What-If execution -> 403 Forbidden
    res_whatif_viewer = client.post(
        "/api/planning/whatif",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"scenario_type": "AIRCRAFT_UNAVAILABLE", "entity_id": "DEMO-A001"}
    )
    assert res_whatif_viewer.status_code == 403


# ── TEST 10: Admin direct login without MFA ───────────────────────────────────
def test_gap_10_admin_direct_login_no_mfa(admin_credentials):
    db = next(get_db())
    admin = db.query(User).filter(User.username == "admin").first()
    assert admin.mfa_enabled is False

    # Login with username & password directly yields access_token
    res_login = client.post("/api/auth/login", json=admin_credentials)
    assert res_login.status_code == 200
    data = res_login.json()

    assert data.get("requires_mfa") is not True
    assert "access_token" in data and data["access_token"] is not None

    # Call protected endpoint with access_token succeeds
    res_protected = client.get("/api/bases", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert res_protected.status_code == 200
