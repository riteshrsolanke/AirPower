# ✈ Air Power — Dynamic Air Operations & Resource Optimisation
### Problem Statement 26250 | SIH 2026 Demonstration Prototype

> **⚠ DISCLAIMER:** This is a training and demonstration prototype using **synthetic aircraft data only**. Not connected to operational defence systems. All data is simulated.

---

## 🚀 Quick Start (macOS)

```bash
# 1. Install Python dependencies
pip3 install fastapi uvicorn sqlalchemy pydantic "passlib[argon2]" argon2-cffi cryptography python-jose pyotp qrcode \
  pillow python-multipart slowapi numpy pandas scikit-learn joblib "bcrypt==4.0.1" pulp pytest pytest-cov httpx

# 2. Seed the database (creates 30 synthetic aircraft + demo accounts)
python3 seed_database.py

# 3. Start the backend (Terminal 1)
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# 4. Start the frontend (Terminal 2)
python3 -m http.server 8080 --directory frontend

# 5. Open in browser
open http://localhost:8080
```

## 🪟 Quick Start (Windows)
We've included a batch script to automate the startup process for Windows users. Make sure you have installed the Python dependencies first (step 1 above).
```cmd
# Double click the file or run in command prompt:
run_windows.bat
```

---

## 🔐 Demo Credentials

| Role               | Username         | Password          |
|--------------------|------------------|-------------------|
| ADMIN              | admin            | Admin@Demo2026!   |
| MAINTENANCE_MANAGER| maintenance_mgr  | Maint@Demo2026!   |
| ANALYST            | analyst          | Analyst@Demo2026! |
| VIEWER             | viewer           | Viewer@Demo2026!  |

---

## 🎯 Complete Demo Flow (43 Steps)

```
LOGIN → DASHBOARD → SELECT AIRCRAFT → DIGITAL TWIN
     → START SIMULATION → SENSOR VALUES CHANGE
     → AI DETECTS ANOMALY → FAILURE RISK INCREASES
     → RUL DECREASES → ALERT GENERATED
     → SPARE SHORTAGE DETECTED → MAINTENANCE RECOMMENDATION
     → FLEET AVAILABILITY UPDATED → GENERATE REPORT
     → VIEW AUDIT LOG → LOGOUT
```

**Use Demo Mode → "RUN COMPLETE DEMO"** to execute this automatically.

---

## 📐 Architecture

```
26250/
├── backend/
│   └── app/
│       ├── main.py           # FastAPI application entry
│       ├── core/
│       │   ├── config.py     # Settings from environment
│       │   ├── security.py   # bcrypt, JWT, TOTP MFA
│       │   └── deps.py       # Auth dependencies + RBAC
│       ├── db/
│       │   └── database.py   # SQLite/PostgreSQL connection
│       ├── models/
│       │   └── models.py     # SQLAlchemy ORM models
│       ├── api/
│       │   ├── auth.py       # Login, MFA, refresh, logout
│       │   ├── aircraft.py   # Fleet, detail, sensors, prediction
│       │   ├── maintenance.py# Maintenance CRUD
│       │   └── extras.py     # Spares, alerts, demo, reports, audit
│       ├── ml/
│       │   └── predictor.py  # RandomForest + IsolationForest
│       └── services/
│           └── simulation.py # Sensor degradation simulator
├── frontend/
│   ├── index.html            # Single-page app shell
│   ├── styles.css            # Dark professional design system
│   └── app.js               # Complete JS frontend
├── ml/
│   └── models/               # Trained model files (auto-generated)
├── seed_database.py          # Database seeder with demo data
├── .env                      # Environment config (not committed)
└── README.md
```

---

## 🤖 ML Pipeline

- **Risk Classifier**: RandomForestClassifier (100 trees, 3 classes: healthy/warning/critical)
- **RUL Regressor**: GradientBoostingRegressor (estimates remaining flight hours)
- **Anomaly Detector**: IsolationForest (trained on healthy-only samples)
- **Training data**: 2000 synthetic sensor records, 6 features
- **Features**: engine_temperature, vibration, oil_pressure, fuel_consumption, hydraulic_pressure, operating_hours

> ⚠ AI predictions are generated using synthetic demonstration data and are not validated for operational aircraft maintenance.

---

## 🔒 Security Architecture

| Feature | Implementation |
|---------|---------------|
| Password hashing | bcrypt via passlib |
| Authentication | JWT (HS256), short-lived access + refresh rotation |
| MFA | TOTP (RFC 6238) with QR code enrollment |
| RBAC | 4 roles, enforced server-side on every endpoint |
| Rate limiting | slowapi (60 req/min, 5 failed logins → 15min lockout) |
| SQL injection | SQLAlchemy ORM with parameterized queries |
| XSS | Output encoding, no eval/exec |
| CORS | Strict whitelist |
| Security headers | X-Frame-Options, X-Content-Type-Options, XSS-Protection |
| Audit trail | Immutable log of all security events |

---

## 🗄 Database Schema

**Tables:** users, refresh_tokens, aircraft, aircraft_components, sensor_readings, predictions, maintenance_records, spare_parts, alerts, audit_logs, demo_scenarios

---

## 🌐 API Endpoints

| Method | Path | Auth |
|--------|------|------|
| POST | /api/auth/login | Public |
| POST | /api/auth/mfa/verify | Public |
| POST | /api/auth/refresh | Public |
| POST | /api/auth/logout | Any |
| GET | /api/aircraft | Any |
| GET | /api/aircraft/statistics | Any |
| GET | /api/aircraft/{id} | Any |
| GET | /api/aircraft/{id}/sensors | Any |
| POST | /api/aircraft/{id}/predict | Analyst+ |
| GET | /api/maintenance | Any |
| POST | /api/maintenance | Manager+ |
| PATCH | /api/maintenance/{id} | Manager+ |
| GET | /api/spares | Any |
| PATCH | /api/spares/{id}/stock | Manager+ |
| GET | /api/spares/predictions/shortage | Analyst+ |
| GET | /api/alerts | Any |
| PATCH | /api/alerts/{id} | Any |
| POST | /api/demo/start | Analyst+ |
| POST | /api/demo/step | Analyst+ |
| POST | /api/demo/reset | Manager+ |
| GET | /api/fleet/availability | Any |
| GET | /api/reports/fleet-health | Analyst+ |
| GET | /api/audit-logs | Admin only |
| GET | /api/users | Admin only |

Full interactive docs: **http://localhost:8000/api/docs**

---

## 🧪 Quick Verification

```bash
# Run the complete PyTest suite (Covers phases 1 through 6)
python3 -m pytest tests/backend/test_api.py -v

# Or manually test login with cURL
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@Demo2026!"}'

# Test health
curl http://localhost:8000/api/health

# Test unauthorized access (should return 403)
curl -H "Authorization: Bearer fake-token" http://localhost:8000/api/audit-logs
```

---

## 📝 Limitations (Prototype)

- SQLite used for simplicity (PostgreSQL supported via `DATABASE_URL`)
- ML model trained on 2000 synthetic samples (not real aircraft data)
- RUL estimation is a synthetic demonstration, not an operationally validated model
- MFA QR code enrollment requires an authenticator app

## 🔮 Future Scope

- Real IoT sensor integration via MQTT/WebSocket
- PostgreSQL + TimescaleDB for sensor data
- LSTM-based RUL models trained on real maintenance datasets
- Mobile app for field technicians
- Integration with ERP/MRO systems
- Multi-base federated fleet management

---

*Prototype for training and demonstration using synthetic data. Not connected to operational defence systems.*
