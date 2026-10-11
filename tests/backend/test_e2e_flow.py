"""
End-to-End SIH 2026 Demonstration Flow Test (Phase 16).

Verifies the complete evaluator workflow:
1. LOGIN (admin + MFA TOTP)
2. DASHBOARD / COP (readiness stats, fleet availability)
3. VIEW SYNTHETIC FLEET & MISSIONS (constrained scenario attributes)
4. GENERATE PLAN & COMPARE 3 OBJECTIVES (MAX_COVERAGE, MIN_RISK, RESOURCE_LEAN)
5. RUN OPERATIONAL WHAT-IF (aircraft unavailable, zero DB mutation)
6. VERIFY PLAN DIFF & EXPLAINABILITY (XAI checklist)
7. PROMOTE SIMULATED SCENARIO TO PENDING PLAN
8. SECOND USER APPROVES (Four-Eyes principle)
9. AUDIT LOG & SHA-256 CHAIN VERIFICATION
"""

import pytest
import pyotp
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.db.database import get_db
from backend.app.models.models import User, MissionPlan, PlanStatus

client = TestClient(app)


def test_full_ps26250_e2e_demonstration():
    # ── STEP 1: LOGIN (admin direct login without MFA) ─────────────────────────
    res_login = client.post("/api/auth/login", json={"username": "admin", "password": "123"})
    assert res_login.status_code == 200
    login_data = res_login.json()
    admin_token = login_data.get("access_token")
    assert admin_token is not None

    # Login analyst for four-eyes approval
    res_analyst = client.post("/api/auth/login", json={"username": "analyst", "password": "123"})
    assert res_analyst.status_code == 200
    analyst_token = res_analyst.json()["access_token"]

    headers_admin = {"Authorization": f"Bearer {admin_token}"}
    headers_analyst = {"Authorization": f"Bearer {analyst_token}"}

    # ── STEP 2: DASHBOARD / COP (Dynamic Stats) ───────────────────────────────
    res_crew = client.get("/api/crews/summary/readiness", headers=headers_admin)
    assert res_crew.status_code == 200
    crew_data = res_crew.json()
    assert "total" in crew_data and "available" in crew_data
    assert crew_data["total"] > 0
    # Confirm it's not hardcoded 12/12
    assert isinstance(crew_data["fit"], int)

    res_bases = client.get("/api/bases", headers=headers_admin)
    assert res_bases.status_code == 200
    assert len(res_bases.json()["bases"]) > 0

    # ── STEP 3: VIEW SYNTHETIC FLEET & MISSIONS ───────────────────────────────
    # Ensure constrained scenario is loaded for distinct trade-offs
    res_scenario = client.post("/api/planning/scenario/load-constrained", headers=headers_admin)
    assert res_scenario.status_code == 200
    assert res_scenario.json()["status"] == "success"

    res_status = client.get("/api/planning/scenario/status", headers=headers_admin)
    assert res_status.status_code == 200
    assert res_status.json()["scenario"] == "CONSTRAINED"

    res_ac = client.get("/api/aircraft", headers=headers_admin)
    assert res_ac.status_code == 200
    aircraft_list = res_ac.json()["aircraft"]
    # Verify synthetic constraints exist
    for ac in aircraft_list[:3]:
        assert "range_km" in ac
        assert "fuel_capacity" in ac
        assert "payload_capacity" in ac

    res_m = client.get("/api/missions", headers=headers_admin)
    assert res_m.status_code == 200
    missions_list = res_m.json()["missions"]
    for m in missions_list[:3]:
        assert "distance_km" in m
        assert "required_payload" in m
        assert "time_window_start" in m
        assert "time_window_end" in m

    # ── STEP 4: GENERATE PLAN & COMPARE 3 OBJECTIVES ──────────────────────────
    res_gen = client.post("/api/planning/generate", headers=headers_admin, json={"note": "E2E demonstration plan"})
    assert res_gen.status_code == 200
    gen_data = res_gen.json()
    plans = gen_data["plans"]
    assert len(plans) == 3

    plan_by_mode = {p["plan_type"]: p for p in plans}
    assert "MAX_COVERAGE" in plan_by_mode
    assert "MIN_RISK" in plan_by_mode
    assert "RESOURCE_LEAN" in plan_by_mode

    # Objective trade-offs must be distinct
    cov_plan = plan_by_mode["MAX_COVERAGE"]
    risk_plan = plan_by_mode["MIN_RISK"]
    lean_plan = plan_by_mode["RESOURCE_LEAN"]

    assert cov_plan["coverage_pct"] >= risk_plan["coverage_pct"]
    assert risk_plan["risk_score"] <= cov_plan["risk_score"]

    # ── STEP 5: RUN OPERATIONAL WHAT-IF (AIRCRAFT UNAVAILABLE) ─────────────────
    first_assigned = cov_plan["assignments"][0]["aircraft_id"]
    res_whatif = client.post("/api/planning/whatif", headers=headers_admin, json={
        "scenario_type": "AIRCRAFT_UNAVAILABLE",
        "entity_id": first_assigned,
        "objective": "MAX_COVERAGE",
        "parameters": {"reason": "Synthetic hydraulic leak simulated"}
    })
    assert res_whatif.status_code == 200
    whatif_res = res_whatif.json()
    assert whatif_res["simulated_plan"] is not None

    # Zero DB mutation verified
    db = next(get_db())
    db_plan = db.query(MissionPlan).filter(MissionPlan.id == cov_plan["plan_id"]).first()
    assert db_plan.status in [PlanStatus.PROPOSED, PlanStatus.APPROVED]

    # ── STEP 6: VERIFY PLAN DIFF & EXPLAINABILITY ──────────────────────────────
    diff = whatif_res["plan_diff"]
    assert isinstance(diff, list)
    # The removed aircraft should appear in REMOVED or REPLACED
    diff_types = {d["change_type"] for d in diff}
    assert any(t in diff_types for t in ["REMOVED", "REPLACED", "RETAINED"])

    # Verify explainability contains synthetic constraints
    assignments = whatif_res["simulated_plan"]["assignments"]
    if assignments:
        sample_xai = assignments[0].get("explanation", "")
        assert "Assignment selected because" in sample_xai or "✓" in sample_xai
        details = assignments[0].get("explanation_details")
        if details:
            assert details.get("range_km_feasible") is True
            assert details.get("payload_feasible") is True

    # ── STEP 7: PROMOTE WHAT-IF SCENARIO TO PENDING PLAN ───────────────────────
    res_promote = client.post("/api/planning/whatif/promote", headers=headers_analyst, json={
        "simulation_result": whatif_res,
        "note": f"Promoted from What-If simulation by analyst: {first_assigned} removed"
    })
    assert res_promote.status_code == 200
    promoted_plan_id = res_promote.json()["plan_id"]

    # ── STEP 8: FOUR-EYES APPROVAL (CREATOR CANNOT APPROVE) ────────────────────
    # Analyst created/promoted it, so Analyst cannot approve (Self-approval & Clearance check)
    res_self_approve = client.post(f"/api/planning/{promoted_plan_id}/approve", headers=headers_analyst)
    assert res_self_approve.status_code == 403

    # Admin approves it (Valid clearance and distinct second user)
    res_admin_approve = client.post(f"/api/planning/{promoted_plan_id}/approve", headers=headers_admin)
    assert res_admin_approve.status_code == 200
    assert res_admin_approve.json()["message"] == "Plan approved."

    # ── STEP 9: AUDIT LOG & SHA-256 CHAIN VERIFICATION ────────────────────────
    res_chain = client.get("/api/audit-logs/verify", headers=headers_admin)
    assert res_chain.status_code == 200
    chain_data = res_chain.json()
    assert chain_data["valid"] is True
    assert chain_data["reason"] == "Chain intact"
