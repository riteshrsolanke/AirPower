import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.models.models import Crew, CrewDutyLog, CrewOverride, User, UserRole
from backend.app.db.database import SessionLocal
from backend.app.core.security import hash_password

@pytest.fixture
def test_db():
    db = SessionLocal()
    yield db
    db.close()

def test_override_requires_second_user(test_db):
    client = TestClient(app)
    
    import uuid
    uid = str(uuid.uuid4())[:8]
    # Create two manager users
    u1 = User(email=f"m1_{uid}@t.com", username=f"m1_{uid}", hashed_password=hash_password("pw"), role=UserRole.MAINTENANCE_MANAGER)
    u2 = User(email=f"m2_{uid}@t.com", username=f"m2_{uid}", hashed_password=hash_password("pw"), role=UserRole.MAINTENANCE_MANAGER)
    test_db.add_all([u1, u2])
    test_db.commit()
    
    # Create a crew
    c = Crew(name="Test Crew UNFIT", rank="Flt Lt", role="PILOT")
    test_db.add(c)
    test_db.commit()
    
    # Create fatigue logs to make crew UNFIT (score > 70)
    now = datetime.utcnow()
    # 1. Long duty yesterday (12 hours)
    test_db.add(CrewDutyLog(crew_id=c.id, start_time=now-timedelta(hours=36), end_time=now-timedelta(hours=24)))
    # 2. Long duty today (15 hours) with night flag
    test_db.add(CrewDutyLog(crew_id=c.id, start_time=now-timedelta(hours=18), end_time=now-timedelta(hours=3), night_flag=True))
    # 3. Many night sorties today to push score > 70
    for i in range(8):
        test_db.add(CrewDutyLog(crew_id=c.id, start_time=now-timedelta(hours=2, minutes=i*10), end_time=now-timedelta(hours=1, minutes=i*10), night_flag=True))
    test_db.commit()
    
    # Mock token for u1
    from backend.app.core.security import create_access_token
    token1 = create_access_token({"sub": u1.id, "role": "MAINTENANCE_MANAGER"})
    token2 = create_access_token({"sub": u2.id, "role": "MAINTENANCE_MANAGER"})
    
    # Request override as u1
    resp = client.post(f"/api/crew/{c.id}/override-request", 
                       json={"justification": "Emergency"},
                       headers={"Authorization": f"Bearer {token1}"})
    if resp.status_code != 200:
        print("Response:", resp.json())
        print("Score data:", client.get(f"/api/crew/{c.id}/fatigue", headers={"Authorization": f"Bearer {token1}"}).json())
    assert resp.status_code == 200
    override_id = resp.json()["override_id"]
    
    # Try to approve as u1 (should fail, four eyes)
    resp = client.post(f"/api/crew/override/{override_id}/approve",
                       headers={"Authorization": f"Bearer {token1}"})
    assert resp.status_code == 403
    
    # Approve as u2 (should succeed)
    resp = client.post(f"/api/crew/override/{override_id}/approve",
                       headers={"Authorization": f"Bearer {token2}"})
    assert resp.status_code == 200
    
    # Check DB
    ov = test_db.query(CrewOverride).filter(CrewOverride.id == override_id).first()
    assert ov.status == "APPROVED"
    assert ov.approved_by == u2.id
