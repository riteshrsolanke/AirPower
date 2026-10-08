import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)

@pytest.fixture(scope="module")
def admin_token():
    res = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@Demo2026!"})
    data = res.json()
    if data.get("requires_mfa"):
        from backend.app.db.database import get_db
        from backend.app.models.models import User
        import pyotp
        db = next(get_db())
        user = db.query(User).filter(User.username == "admin").first()
        code = pyotp.TOTP(user.mfa_secret).now()
        res_mfa = client.post("/api/auth/mfa/verify", json={"temp_token": data["temp_token"], "code": code})
        return res_mfa.json()["access_token"]
    return data["access_token"]

@pytest.fixture(scope="module")
def analyst_token():
    res = client.post("/api/auth/login", json={"username": "analyst", "password": "Analyst@Demo2026!"})
    return res.json()["access_token"]

@pytest.fixture(scope="module")
def viewer_token():
    res = client.post("/api/auth/login", json={"username": "viewer", "password": "Viewer@Demo2026!"})
    return res.json()["access_token"]


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_auth_failure():
    response = client.post("/api/auth/login", json={"username": "admin", "password": "WrongPassword"})
    assert response.status_code == 401


def test_get_bases(analyst_token):
    res = client.get("/api/bases", headers={"Authorization": f"Bearer {analyst_token}"})
    assert res.status_code == 200
    assert "bases" in res.json()


def test_get_aircraft(viewer_token):
    res = client.get("/api/aircraft", headers={"Authorization": f"Bearer {viewer_token}"})
    assert res.status_code == 200
    assert "aircraft" in res.json()


def test_generate_and_approve_plan(analyst_token, admin_token):
    # Analyst generates plan
    res = client.post("/api/planning/generate", headers={"Authorization": f"Bearer {analyst_token}"}, json={"note": "Pytest generated"})
    assert res.status_code == 200
    plans = res.json()["plans"]
    assert len(plans) > 0
    
    plan_id = plans[0]["plan_id"]
    
    # Analyst attempts to approve their own plan (Four-eyes violation / Clearance violation)
    res_approve_fail = client.post(f"/api/planning/{plan_id}/approve", headers={"Authorization": f"Bearer {analyst_token}"})
    assert res_approve_fail.status_code == 403
    
    # Admin approves the plan (Valid clearance and didn't create the plan)
    res_approve_success = client.post(f"/api/planning/{plan_id}/approve", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_approve_success.status_code == 200
    assert res_approve_success.json()["message"] == "Plan approved."


def test_fusion_ingest(admin_token):
    # Test data fusion layer (Phase 5)
    payload = {
        "event_id": "TEST-FUSION-123",
        "timestamp": "2026-10-04T12:00:00Z",
        "aircraft_tail_number": "A001",
        "fault_code": "HYD-LOW",
        "severity": "CRITICAL"
    }
    res = client.post("/api/feeds/aircraft_health/ingest", headers={"Authorization": f"Bearer {admin_token}"}, json=payload)
    assert res.status_code == 200
    assert res.json()["status"] in ["success", "ignored"]


def test_audit_chain_verification(admin_token):
    # Test Audit Chain verification (Phase 6)
    res = client.get("/api/audit-logs/verify", headers={"Authorization": f"Bearer {admin_token}"})
    assert res.status_code == 200
    assert res.json()["valid"] == True
