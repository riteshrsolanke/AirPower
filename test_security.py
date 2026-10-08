import requests
import json

BASE_URL = "http://localhost:8000/api"

print("--- Phase 6 Test ---")

# We login as analyst
res = requests.post(f"{BASE_URL}/auth/login", json={"username": "analyst", "password": "Analyst@Demo2026!"})
token = res.json().get("access_token")
headers = {"Authorization": f"Bearer {token}"}
print("Analyst Login:", res.status_code)

# Analyst creates a plan
res = requests.post(f"{BASE_URL}/planning/generate", headers=headers, json={"note": "Test four eyes"})
print("Generate plan:", res.status_code)
plans = requests.get(f"{BASE_URL}/planning", headers=headers).json().get("plans", [])
if not plans:
    print("No plan generated!")
    exit(1)
latest_plan_id = plans[-1]["id"]
print("Plan ID:", latest_plan_id)

# Analyst tries to approve it
res = requests.post(f"{BASE_URL}/planning/{latest_plan_id}/approve", headers=headers)
print("Analyst Approve (should fail Four-Eyes):", res.status_code, res.json())

# Wait, the analyst might not even have SECRET clearance. Let's see. 
# We login as manager (if manager has SECRET clearance and didn't create the plan).
res = requests.post(f"{BASE_URL}/auth/login", json={"username": "manager", "password": "Manager@Demo2026!"})
token2 = res.json().get("access_token")
headers2 = {"Authorization": f"Bearer {token2}"}
print("\nManager Login:", res.status_code)

res = requests.post(f"{BASE_URL}/planning/{latest_plan_id}/approve", headers=headers2)
print("Manager Approve (should fail if clearance is UNCLASSIFIED, or succeed if updated):", res.status_code, res.json())

# Test Audit Chain
res = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "Admin@Demo2026!"})
token3 = res.json().get("access_token")
headers3 = {"Authorization": f"Bearer {token3}"}
print("\nAdmin Login:", res.status_code)

res = requests.get(f"{BASE_URL}/audit-logs/verify", headers=headers3)
print("Audit Chain Verification:", res.status_code, res.json())
