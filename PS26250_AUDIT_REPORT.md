# AIRPOWER PS 26250 PROTOTYPE AUDIT

> **Audited:** 2026-10-08 | **Auditor:** Senior Defence Systems Architect / SIH Evaluator  
> **Method:** Complete source-code trace — FRONTEND → API → BACKEND → DATABASE → AI/ML → OPTIMIZATION → DECISION ENGINE  
> **Scope:** `/Users/shreyas/Desktop/26250/` — all files read, nothing assumed.

---

## 1. Executive Summary

This prototype is **substantially more aligned with PS 26250 than a typical SIH submission**, but it contains a **significant PS 26249 legacy layer** (predictive maintenance + sensor simulation) that partially dilutes the PS 26250 message. The core air-operations stack — MILP optimizer, dynamic retasker, human approval workflow, explainable assignments, and cryptographic audit chain — is **genuinely implemented with working code**. The gaps are: the **What-If engine** (maintenance-centric, not operational), some **frontend hardcoded values**, and the **absence of range/fuel/time-window modelling** in the MILP.

**Overall PS 26250 Alignment: 68%**

**Final Verdict: ALIGNED WITH MAJOR FIXES**

---

## 2. What the Prototype Actually Does (Code-Confirmed)

| Layer | What exists (real code) |
|---|---|
| **Database** | 30 aircraft, 8 missions, 31 crew, 4 bases, 8 weapon types, threat zones, airspace zones, weather, data feeds, mission plans, plan assignments, event logs, audit chain |
| **MILP Optimizer** | PuLP/CBC solver — 3 objective functions (MAX_COVERAGE, MIN_RISK, RESOURCE_LEAN), real MILP constraints, crew selection, weapon compatibility |
| **Dynamic Retasker** | 7 event types handled, incremental MILP reoptimization, plan diff computation |
| **Human Approval** | PROPOSED → APPROVED/REJECTED workflow with four-eyes rule + ABAC clearance gate |
| **Audit Chain** | SHA-256 Merkle-style chained audit log with tamper detection endpoint |
| **Security** | Argon2id passwords, RS256 JWT, TOTP MFA, RBAC (4 roles), account lockout, rate limiting |
| **ML Models** | RandomForest (failure risk), GradientBoostingRegressor×3 (quantile RUL), IsolationForest (anomaly) — all synthetic-data-trained |
| **Fatigue Model** | Rule-based: duty hours, night sorties, circadian penalty → FIT/CAUTION/UNFIT |
| **Data Fusion** | Feed ingestion → normalise → event injection → retask pipeline |
| **Frontend** | Login/MFA, fleet dashboard, aircraft detail, demo simulation, COP page, planning page, crew fatigue, alert management |

---

## 3. PS 26250 Requirements vs Implementation

| PS 26250 Requirement | Status | Evidence |
|---|---|---|
| Mission planning entities in DB | ✅ IMPLEMENTED | `models.py` lines 566–741: Mission, Crew, AirBase, WeaponType, AircraftWeaponCompat, ThreatZone, AirspaceZone, WeatherCondition |
| MILP optimization engine | ✅ IMPLEMENTED | `optimizer.py` lines 375–505: PuLP CBC, LpBinary variables, real constraints |
| Aircraft-to-mission assignment | ✅ IMPLEMENTED | `generate_plans()` → PlanAssignment records with explanation |
| Crew selection with qualifications | ✅ IMPLEMENTED | `_pick_crew()` lines 247–288: qualification, base, duty hours, fatigue |
| Weapon compatibility constraints | ✅ IMPLEMENTED | Lines 189–201: `weapon_compat` set + inventory check |
| Weather go/no-go constraint | ✅ IMPLEMENTED | Lines 203–210: `weather_map.get(aircraft.base_id)` blocks NOGO bases |
| Threat exposure scoring | ✅ IMPLEMENTED | `_threat_exposure()` lines 121–141: haversine + severity weighting |
| Dynamic retasking on aircraft failure | ✅ IMPLEMENTED | `retasker.py` `_apply_aircraft_unserviceable()` + incremental MILP |
| Dynamic retasking on weather | ✅ IMPLEMENTED | `_apply_weather_closure()` → refetch weather → MILP |
| Dynamic retasking on new threat | ✅ IMPLEMENTED | `_apply_new_threat()` → recompute threat scores |
| Dynamic retasking on crew unavailable | ✅ IMPLEMENTED | `_apply_crew_unavailable()` → mission replanned |
| Dynamic retasking on new P1 mission | ✅ IMPLEMENTED | `_apply_new_priority_mission()` injects mission + retask |
| Plan diff (before/after) | ✅ IMPLEMENTED | `compute_plan_diff()` → ADDED/REMOVED/REPLACED/RETAINED |
| Human approval workflow | ✅ IMPLEMENTED | `POST /api/planning/{id}/approve` with four-eyes + ABAC clearance |
| Explainable assignment | ✅ IMPLEMENTED | `_explain_assignment()` → natural-language reasoning per assignment |
| Audit log | ✅ IMPLEMENTED | SHA-256 chained `AuditLog` table, `verify_chain()` endpoint |
| JWT + RBAC | ✅ IMPLEMENTED | RS256 JWT, 4 roles, `require_analyst_or_above` on all planning endpoints |
| Crew fatigue model | ✅ IMPLEMENTED | `fatigue.py`: 7 weighted factors → FIT/CAUTION/UNFIT |
| Crew override with four-eyes | ✅ IMPLEMENTED | `crew.py` request_override + approve_override with self-approval block |
| Multiple aircraft per mission | ✅ IMPLEMENTED | `min_aircraft_count` in Mission, MILP enforces N-aircraft requirement |
| Operational What-If | ❌ NOT PS 26250 | `runWhatIf()` calls `/aircraft/{id}/whatif` — maintenance RUL projection only |
| Mission fuel/range constraint | ❌ MISSING | No `range_km`, `fuel_kg`, `payload_kg` in Aircraft schema |
| Airspace closure as hard MILP constraint | 🟡 PARTIAL | Recorded in DB, advisory note only — not a hard MILP exclusion |
| Base capacity constraint | ❌ MISSING | `max_aircraft_capacity` in AirBase schema, not used in optimizer |
| Time window enforcement in MILP | ❌ MISSING | `time_window_start/end` exist in Mission — not checked by optimizer |

---

## 4. PS 26249 vs PS 26250 Layer Analysis

### PS 26249 features present in the codebase:

| Feature | Assessment for PS 26250 |
|---|---|
| Sensor readings (engine temp, vibration, oil pressure, hydraulic) | **RETAIN as health feed** — only relevant as RUL input |
| RUL prediction (GradientBoosting quantile) | **RETAIN** — feeds mission feasibility: `rul_hours >= duration + 20h` |
| Anomaly detection (IsolationForest) | **RETAIN** — can trigger aircraft_unserviceable event |
| Demo simulation (engine/hydraulic/complete_failure anomalies) | **DEMOTE** — shows sensor degradation, not ops planning |
| Maintenance records, spare parts | **DEMOTE** — irrelevant to PS 26250 |
| What-If (extra hours → RUL projection) | **REPLACE** with operational What-If |
| Fleet health dashboard with RUL charts | **REFRAME** as fleet availability input to optimizer |

### Critical Integration (GENUINE — code-proven):
```
Aircraft Sensor Data
       ↓
RUL / Health Prediction (ML)
       ↓
mission_capable_status = CAPABLE / LIMITED / GROUNDED
       ↓
Optimizer Constraint: aircraft excluded if GROUNDED (optimizer.py line 519)
       ↓
Mission Assignment respects aircraft health
```
This chain is **real and implemented**. The PS 26249 ML layer feeds the PS 26250 optimizer correctly.

---

## 5. Optimization Engine Audit

### Algorithm: MILP via PuLP + CBC (optimizer.py lines 39–42)

**Decision Variables:**
- `x[m, a]` ∈ {0,1} — aircraft `a` assigned to mission `m`
- `cov[m]` ∈ {0,1} — mission `m` is covered

### Three Objective Functions (genuinely distinct):

| Plan Type | Objective Formula | Code Location |
|---|---|---|
| MAX_COVERAGE | `Σ priority_weight[m] × cov[m]` | Line 416 |
| MIN_RISK | Coverage − 2.5 × `Σ threat_score[m] × x[m,a]` | Lines 422–427 |
| RESOURCE_LEAN | Coverage − 0.15 × total sorties | Lines 429–432 |

### Hard Constraints:

| Constraint | Implemented | Location |
|---|---|---|
| Aircraft GROUNDED excluded | ✅ | `_load_context()` line 519 + feasibility check line 160 |
| RUL ≥ mission_duration + 20h margin | ✅ | Lines 173–180 |
| Aircraft type must match | ✅ | Lines 183–186 |
| Weapon compatible + in stock | ✅ | Lines 189–201 |
| Weather GO at base | ✅ | Lines 203–210 |
| Each aircraft used ≤ once | ✅ | Lines 463–466 |
| Plan diversity (N+1 ≠ N) | ✅ | Lines 469–483: forbidden pair sets |
| **Base capacity** | ❌ MISSING | `max_aircraft_capacity` unused |
| **Time window feasibility** | ❌ MISSING | `time_window_start/end` unused |
| **Range/fuel** | ❌ MISSING | No field in Aircraft schema |

**Solve time:** 4-second limit. Actual: < 1s (8 missions, 30 aircraft).

**Live DB results:** 3 plans exist — v1=APPROVED (MAX_COVERAGE, 100%), v2=PROPOSED (MIN_RISK, 100%), v3=PROPOSED (RESOURCE_LEAN, 100%). All 8 missions covered in all 3 plans. **This 100% coverage with 30 aircraft vs 8 missions means the scenario is too easy — zero visible constraint pressure.**

---

## 6. Dynamic Retasking Audit

### Event types handled (retasker.py):

| Event | Effect | Mission Invalidation | MILP Retask | Status |
|---|---|---|---|---|
| AIRCRAFT_UNSERVICEABLE | Aircraft → GROUNDED, failure_risk bumped | ✅ | ✅ | **IMPLEMENTED** |
| WEATHER_CLOSURE | WeatherCondition.is_go = False | ✅ Aircraft at that base | ✅ | **IMPLEMENTED** |
| NEW_THREAT | New ThreatZone inserted | ✅ Missions with exposure > 0.5 | ✅ | **IMPLEMENTED** |
| CREW_UNAVAILABLE | Crew.is_available = False, MANDATORY_REST | ✅ | ✅ | **IMPLEMENTED** |
| NEW_PRIORITY_MISSION | New Mission (P1/P2) created | Lock existing, plan new | ✅ | **IMPLEMENTED** |
| AIRSPACE_CLOSURE | AirspaceZone.is_active = True | ❌ Advisory only | ❌ | **PARTIAL** |
| FEED_DEGRADED | DataFeed.status = STALE | ❌ No invalidation | N/A | **PARTIAL** |

### Retask flow (verified end-to-end in code):
```
EventLog created → process_event() →
  1. _apply_*() mutates DB state
  2. _find_affected_missions() invalidates PlanAssignments
  3. retask_missions() incremental MILP on affected missions only
  4. Old plan → SUPERSEDED
  5. New plan → PROPOSED (awaits human approval)
  6. compute_plan_diff() → ADDED/REMOVED/REPLACED/RETAINED
  7. EventLog.resulting_plan_id set + replanning_time_ms recorded
```

**Note:** `event_logs` table has 0 rows — fresh DB state, no events injected yet.

---

## 7. What-If Scenario Audit

### Current What-If (app.js line 2207):
```javascript
const data = await api('POST', `/aircraft/${aircraftId}/whatif`, {
  extra_hours: hours,
  profile: profile
});
// Shows: RUL trajectory, anomaly score, warning/critical hours
```

**This is 100% PS 26249** — simulates extra flight hours on a single aircraft, projects RUL degradation. Does NOT change any mission assignment or show operational impact.

### What PS 26250 requires instead:

| Operational What-If | Exists? |
|---|---|
| "Remove aircraft X from pool → new plan" | ❌ |
| "Pilot Y unavailable → mission impact" | ❌ |
| "Weather closes Base Alpha → alternatives" | ❌ |
| "Weapon stock drops → dropped missions" | ❌ |
| "Add P1 emergency mission → preemption" | ❌ (available as event, not What-If UI) |

**The What-If engine must be rebuilt as an operational sandbox that calls `generate_plans()` with modified constraints.**

---

## 8. AI/ML Audit

### Models (predictor.py):

| Model | Algorithm | Output | Training Data | Feeds Optimizer? |
|---|---|---|---|---|
| `risk_classifier` | RandomForestClassifier (100 trees, depth 8) | Failure risk [0–1] | 2000 synthetic samples (3 classes) | ✅ → `mission_capable_status` → MILP |
| `rul_regressor_median` | GradientBoostingRegressor (quantile α=0.5) | RUL median (hours) | Same 2000 samples | ✅ → RUL constraint in MILP |
| `rul_regressor_low` | GradientBoostingRegressor (quantile α=0.1) | RUL lower bound | Same | ✅ → conservative feasibility |
| `rul_regressor_high` | GradientBoostingRegressor (quantile α=0.9) | RUL upper bound | Same | ❌ display only |
| `anomaly_detector` | IsolationForest (100 trees) | Anomaly score [0–1] | Healthy samples only | ❌ display only |

### Fatigue Model (fatigue.py) — 7 factors:

| Factor | Weight |
|---|---|
| Duty hours > 8h in last 24h | 2.0/hour |
| Duty hours > 40h in last 7d | 0.5/hour |
| Hours since last rest > 12h | 1.5/hour |
| Night sorties (last 48h) | 10.0/sortie |
| Circadian penalty 02:00–05:00 | 15.0 flat |
| Multiple sorties today | 3.0/sortie > 1 |

Fatigue feeds optimizer: UNFIT crew excluded unless a four-eyes-approved override exists.

### Critical ML Caveats:
1. Training data is **100% synthetic** (numpy seed 42, hand-crafted distributions)
2. "80% confidence" stated without test-set cross-validation
3. ml/models/ `.joblib` files regenerated at startup (not persisted in repo)
4. **RUL is remaining component life, NOT operational range** — different concept

---

## 9. Security Audit

| Control | Status | Evidence |
|---|---|---|
| Argon2id password hashing | ✅ | `security.py` line 23 |
| RS256 JWT (asymmetric) | ✅ | private.pem / public.pem |
| Refresh token rotation | ✅ | SHA-256 hash stored, revoked on rotation |
| TOTP MFA (±1 window) | ✅ | `pyotp`, QR code, 8 recovery codes |
| Account lockout | ✅ | `MAX_LOGIN_ATTEMPTS`, timed unlock |
| RBAC (4 roles) | ✅ | ADMIN, MAINTENANCE_MANAGER, ANALYST, VIEWER |
| ABAC (clearance level) | ✅ | Plan approval requires SECRET/TOP SECRET |
| Four-eyes: plan approval | ✅ | Creator cannot approve own plan |
| Four-eyes: crew override | ✅ | Requester cannot approve own override |
| SHA-256 audit chain | ✅ | `audit.py` — Merkle-style, `verify_chain()` endpoint |
| Rate limiting | ✅ | `slowapi` middleware |
| Security headers | ✅ | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` |
| SQL injection prevention | ✅ | SQLAlchemy ORM parameterised queries |
| Stack trace protection | ✅ | Global exception handler — generic message only |
| CORS | ⚠️ OPEN | `allow_origins=["*"]` — demo caveat |
| MFA defaulted off | ⚠️ | 0/6 users have `mfa_enabled=True` in DB |

**Security score: 82% — one of the strongest components.**

---

## 10. Human-in-the-Loop Audit

### Plan Approval:
```
POST /api/planning/generate   → Plans created (PROPOSED) by ANALYST+
POST /api/planning/{id}/approve → Second user (SECRET+, different ID) approves
  - plan.status must be PROPOSED
  - approver.clearance_level in ["SECRET", "TOP SECRET"]
  - approver.id != plan.created_by  [four-eyes enforced]
  → plan.status = APPROVED + audit logged
POST /api/planning/{id}/reject → Mandatory reason required
```

### Crew Override:
```
POST /api/crew/{id}/override-request → MANAGER+ requests (crew must be UNFIT)
POST /api/crew/override/{id}/approve → Different MANAGER+ approves
  - override.requested_by != current_user.id  [four-eyes enforced]
```

**After any retask event: new plan is PROPOSED, not auto-approved. Human must authorize.**

**Human-in-the-loop: FULLY IMPLEMENTED — including edge-case guards.**

---

## 11. Claim-to-Code Traceability Matrix

| Claim | Actual Code | Status |
|---|---|---|
| "MILP-based resource optimization" | `optimizer.py` `_solve_ilp()` — PuLP CBC, LpBinary | ✅ PROVEN |
| "Dynamic retasking" | `retasker.py` `process_event()` — 7 event types, incremental MILP | ✅ PROVEN |
| "Explainable AI assignments" | `_explain_assignment()` — 300+ char natural-language per assignment | ✅ PROVEN |
| "Human-in-the-loop approval" | `planning.py` approve/reject — four-eyes + ABAC clearance gate | ✅ PROVEN |
| "Crew fatigue modeling" | `fatigue.py` + optimizer exclusion of UNFIT crew | ✅ PROVEN |
| "Threat-aware planning" | `_threat_exposure()` haversine — MIN_RISK objective | ✅ PROVEN |
| "Weather go/no-go" | `weather_map` check in `_check_aircraft_mission_feasibility()` | ✅ PROVEN |
| "TOTP MFA" | `security.py` `verify_totp()` via pyotp | ✅ PROVEN |
| "Cryptographic audit trail" | `audit.py` SHA-256 chain, `/api/audit-logs/verify` | ✅ PROVEN |
| "ML models (RF, GB, IF)" | `predictor.py` — sklearn, synthetic data, 5 models | ✅ PROVEN |
| "What-If operational scenarios" | `runWhatIf()` → maintenance RUL only, NOT mission reallocation | ❌ WRONG PS |
| "Crew readiness: 12/12" | `app.js` line 2084: `'12 / 12'; // Mock for demo` | 🔵 HARDCODED |
| "Real-time data feeds" | `fusion.py` `ingest_feed()` → normalise → event | 🟡 SIMULATED |
| "GIS tactical map" | Leaflet.js — renders bases + threats, no routes | 🟡 PARTIAL |
| "Weapon compatibility" | `AircraftWeaponCompat` table checked before MILP | ✅ PROVEN |

---

## 12. Missing PS 26250 Features

| Gap | Priority | Impact | Effort |
|---|---|---|---|
| Operational What-If (planning sandbox) | P0 | Very High | Medium |
| Hardened seed scenario (resource scarcity) | P0 | High | Easy |
| Fix hardcoded crew readiness "12/12" | P0 | High | Trivial |
| Aircraft range_km / fuel / payload in schema + MILP | P0 | Medium | Medium |
| Time window enforcement in MILP | P1 | High | Medium |
| Base capacity constraint in MILP | P1 | Medium | Easy |
| MFA enabled by default for ADMIN user | P1 | Medium | Trivial |
| Airspace closure as hard MILP exclusion | P1 | Medium | Hard |
| Richer event injection UI (aircraft selector) | P1 | High | Medium |

---

## 13. P0/P1/P2 Fix Plan

### P0 — Block Items (must fix before SIH)

| # | Fix | Why | Effort |
|---|---|---|---|
| **P0-1** | **Operational What-If** — replace RUL chart with planning sandbox. UI sends modified constraints → `generate_plans()` → show plan before/after | Judges will ask "what if aircraft X fails?" — must see plan change, not RUL curve | Medium |
| **P0-2** | **Harden seed scenario** — add 4 contested P1 missions with fewer available aircraft (e.g., mark 12 aircraft as GROUNDED/LIMITED). Target: some missions dropped without optimal planning | 100% coverage on all 3 plans with 30 aircraft vs 8 missions shows no optimization pressure | Easy |
| **P0-3** | **Fix crew readiness widget** — replace hardcoded `'12 / 12'` with real DB query `/api/crews/summary/readiness` → show `available` count | Direct lie in the frontend; judges viewing source will flag this | Trivial |
| **P0-4** | **Add range_km to Aircraft schema and MILP** — migrate DB, add feasibility check: `aircraft.range_km >= mission_distance_km` | Judges with ops background will ask about range; current schema has no answer | Medium |

### P1 — High Value

| # | Fix | Effort |
|---|---|---|
| **P1-1** | MILP time window constraint — add `time_window_start ≤ sortie_start ≤ time_window_end` feasibility check | Medium |
| **P1-2** | Base capacity — add `Σ x[m,a] for a at base_b ≤ base_b.max_aircraft_capacity` MILP constraint | Easy |
| **P1-3** | Seed ADMIN user with `mfa_enabled=True` | Trivial |
| **P1-4** | Event injection UI — add dropdowns for aircraft/crew/base/weapon, reduce need for raw JSON input | Medium |

### P2 — Optional Polish

| # | Fix | Effort |
|---|---|---|
| P2-1 | Airspace closure as hard exclusion (geometry intersection) | Hard |
| P2-2 | Cumulative flight hours per crew (all-time counter) | Easy |
| P2-3 | Historical availability trend from real DB data (not synthetic formula) | Easy |

---

## 14. PS 26250 Alignment Scores

| Dimension | Score | Rationale |
|---|---|---|
| Problem understanding | 85% | Correct domain, some 26249 dilution |
| Air operations planning | 80% | Real MILP; missing range/time-window constraints |
| Dynamic retasking | 85% | 7 event types, full loop, plan diff — excellent |
| Resource optimization | 78% | MILP working; base capacity and time windows missing |
| Mission planning | 72% | Good entity model; no origin base, no time-window enforcement |
| Aircraft allocation | 80% | Health/RUL/weapon/weather constraints all work |
| Crew allocation | 75% | Qualification + fatigue checked; no cumulative hours |
| Weapon allocation | 82% | Compatibility + inventory checked; depletion tracked |
| AI/ML | 65% | Real algorithms; synthetic training data; feeds ops chain |
| What-If / Simulation | 25% | 100% maintenance-oriented; no operational sandbox |
| Human-in-the-loop | 90% | Four-eyes, ABAC clearance, crew override — excellent |
| Security | 82% | Argon2id, RS256, TOTP, RBAC, audit chain — strong |
| Auditability | 88% | SHA-256 chain, verify endpoint, all actions logged |
| Frontend | 55% | Planning/COP functional; What-If wrong; hardcoded values |

### **OVERALL ALIGNMENT: 68%**

---

## 15. 5-Minute SIH Demo Script (Real Features Only)

| Time | Step | Feature | Backend Evidence |
|---|---|---|---|
| 0:00–0:30 | Login as ADMIN | Argon2id, JWT, TOTP MFA prompt | `auth.py`, `security.py` |
| 0:30–1:00 | Fleet dashboard | 30 aircraft, CAPABLE/LIMITED/GROUNDED breakdown, threat map | `/api/aircraft`, `/api/zones/threats` |
| 1:00–1:30 | Mission board | 8 PENDING missions (CAS P1, DCA P1, SEAD P2…), weapon requirements | `/api/missions` |
| 1:30–2:00 | Generate optimal plans | 3 plans in <1s — MAX_COVERAGE / MIN_RISK / RESOURCE_LEAN | `POST /api/planning/generate` |
| 2:00–2:30 | Show assignment explanation | Click assignment → natural-language WHY (health, RUL, crew, weapon, threat) | `plan_assignments.explanation` |
| 2:30–3:00 | Inject AIRCRAFT_UNSERVICEABLE event | Key fighter grounded → retask triggered → plan diff shows REPLACED missions | `POST /api/events` |
| 3:00–3:30 | Plan diff visualization | REPLACED: MISSION-ALPHA: DEMO-A001 → DEMO-A012 — before/after | `GET /api/planning/{id}/diff/{base}` |
| 3:30–4:00 | Approve retask plan | Second user (SECRET clearance) approves — four-eyes enforced | `POST /api/planning/{id}/approve` |
| 4:00–4:30 | Crew fatigue gate | Show UNFIT pilot → request override → different manager approves | `/api/crew`, `/api/crew/override` |
| 4:30–5:00 | Audit chain verification | Full trail: login → generate → event → retask → approve → tamper-check | `GET /api/audit-logs/verify` |

**DO NOT demo:** Sensor simulation (26249), maintenance What-If (wrong PS), spare parts, maintenance records.

---

## 16. Final Verdict

### Genuine Strengths (code-proven):
1. **Real MILP optimizer** — PuLP/CBC, 3 distinct objective functions, 8 hard constraints. Rare in SIH.
2. **Complete dynamic retasking loop** — event → DB mutation → incremental MILP → plan diff → end-to-end.
3. **Human-in-the-loop with four-eyes + ABAC** — enforced at code level, not just UI.
4. **Per-assignment natural-language explanation** — genuine explainable AI.
5. **SHA-256 Merkle audit chain** — with tamper detection API.
6. **Crew fatigue feeds optimizer eligibility** — not a mere display widget.
7. **ML → operational constraint pipeline** — RUL → mission feasibility — genuinely connected.

### Real Gaps:
1. **What-If is entirely wrong for PS 26250** — shows RUL curve, not plan reallocation.
2. **Trivial optimization scenario** — 30 aircraft vs 8 missions = 100% coverage every time. No visible trade-offs.
3. **Range/fuel absent** — judges with aviation background will flag this immediately.
4. **Time windows not enforced** — missions have `time_window_start/end` but optimizer ignores them.
5. **Hardcoded "12/12" crew readiness** — a visible data lie in the frontend.
6. **PS 26249 legacy occupies ~40% of surface** — dilutes the PS 26250 narrative.

---

# **VERDICT: ALIGNED WITH MAJOR FIXES**

Fix the 4 P0 items — operational What-If, hardened scenario, crew readiness fix, aircraft range — and this becomes a **STRONGLY ALIGNED** submission. The optimizer, retasker, and approval chain are rare and genuine. A knowledgeable SIH evaluator will recognize the depth AND catch the What-If gap and the trivial planning scenario.

---

*Audit complete. No code was modified. Await approval before implementation begins.*
