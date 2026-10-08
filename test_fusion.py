import requests
import time

print("Testing Phase 5: Data Fusion Layer")
BASE_URL = "http://localhost:8000/api"

# Get a token
res = requests.post(f"{BASE_URL}/auth/login", json={"username": "analyst", "password": "Analyst@Demo2026!"})
token = res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}

# Create a baseline plan first (if one doesn't exist)
requests.post(f"{BASE_URL}/planning/generate", headers=headers, json={"note": "Fusion Test baseline"})
plans = requests.get(f"{BASE_URL}/planning", headers=headers).json().get("plans", [])
if plans:
    base_plan = plans[-1]
    requests.post(f"{BASE_URL}/planning/{base_plan['id']}/approve", headers=headers)
    print("Baseline plan approved.")

print("Ingesting threat_intel feed...")
threat_payload = {
    "action": "NEW",
    "name": "FUSION-THREAT-02",
    "threat_type": "SAM",
    "lat": 31.3,
    "lon": 76.4,
    "radius": 100.0,
    "severity": 5,
    "notes": "Ingested via fusion layer 2"
}

res = requests.post(f"{BASE_URL}/feeds/threat_intel/ingest", headers=headers, json=threat_payload)
print("Response:", res.status_code, res.json())

print("Ingesting aircraft_health feed...")
ac_payload = {
    "aircraft_id": "DEMO-A002",
    "health_score": 16,
    "status": "GROUNDED",
    "reason": "Engine fault detected by fusion layer"
}

res = requests.post(f"{BASE_URL}/feeds/aircraft_health/ingest", headers=headers, json=ac_payload)
print("Response:", res.status_code, res.json())

print("Test complete.")
