from fastapi.testclient import TestClient
from backend.app.main import app

client = TestClient(app)
res_auth = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@Demo2026!"})
token = res_auth.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

print("Airspace:", client.get("/api/zones/airspace", headers=headers).json().keys())
print("Threats:", client.get("/api/zones/threats", headers=headers).json().keys())
