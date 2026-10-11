# ==============================================================================
# PRESENTATION DECK & EVALUATOR HANDBOOK
# Air Power — Dynamic Air Operations & Resource Optimisation
# Problem Statement ID: 26250 | Smart India Hackathon (SIH) 2026
# ==============================================================================

> **CONFIDENTIALITY & DEMONSTRATION NOTICE:**
> **Academic & Evaluator Decision-Support Prototype Using Synthetic / Simulated Data.**
> All platform telemetry, flight corridors, SAM threat rings, radar installations, and bases are synthetic.

---

## SLIDE 1: TITLE SLIDE
- **Title:** AIR POWER — Dynamic Air Operations & Resource Optimisation
- **Subtitle:** AI-Enabled Common Operating Picture, Multi-Source Tactical Data Fusion & Time-Indexed MILP Re-tasking
- **Problem Statement ID:** 26250
- **Theme:** Logistics & Transportation / Defence Operational Planning
- **Core Value Proposition:** Transitioning military Air Tasking Orders (ATO) from static 24-hour cycles to dynamic, sub-second continuous decision-support under hostile friction.

---

## SLIDE 2: THE OPERATIONAL CHALLENGE (PS 26250)
- **Current Friction in Contested Theatres:**
  - **Information Siloing:** Telemetry from maintenance depots, radar tracks, weather radars, and pilot rosters reside in disconnected systems.
  - **Planning Latency:** Traditional ATO cycles require 12 to 24 hours of manual coordination.
  - **Dynamic Invalidation:** A pop-up Surface-to-Air Missile (SAM) battery or an in-flight hydraulic pump fault abruptly invalidates the static plan, forcing suboptimal, high-risk manual workarounds.
  - **Resource Bottlenecks:** Scarce multirole airframes, crew fatigue duty-time limits, and base fuel/turnaround constraints must be juggled simultaneously.

---

## SLIDE 3: SYSTEM ARCHITECTURE & 5 CORE PILLARS
```
  ┌────────────────────────────────────────────────────────────────────────┐
  │                   1. JDL LEVELS 1–3 DATA FUSION                        │
  │    (Radar, ADS-B, SIGINT, HUMINT -> Exponential Freshness Decay)        │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │           2. COMMON OPERATING PICTURE (COP - Leaflet GIS)              │
  │    (Live Bases, Active Corridors, SAM Threat Rings, Airspace Polygons) │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │           3. TIME-INDEXED MILP OPTIMIZER (x[m, a, w])                  │
  │   (Multi-Wave Sorties, 1.5h Turnaround, Hard 2D Airspace Ray-Casting)   │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │           4. DYNAMIC RETASKING & XAI EXPLAINABILITY                    │
  │      (<300ms Delta Re-Plan, SHA-256 Audited Plan Diff, P(Success))     │
  └───────────────────────────────────┬────────────────────────────────────┘
                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │           5. GOVERNANCE & ZERO-TRUST SECURITY                          │
  │     (Argon2id, RS256 Asymmetric Tokens, TOTP MFA, Four-Eyes Approval)  │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## SLIDE 4: BENCHMARK PERFORMANCE COMPARISON TABLE
*Empirical evaluation across a standard 10-mission, 12-aircraft contested operational scenario.*

| Key Operational Metric | Time-Indexed MILP (PuLP / CBC) | Greedy Priority Heuristic | Manual ATO Baseline | Operational Benefit |
|---|:---:|:---:|:---:|---|
| **Mission Coverage (%)** | **100% (10/10)** | **80% (8/10)** | **60% (6/10)** | Zero mission drops; global asset trade-offs |
| **Cumulative Threat Exposure** | **14.2 (Optimal)** | **22.8 (+60.5%)** | **31.0 (+118.3%)** | Route integrals avoid peak SAM radar lobes |
| **Multi-Wave Turnaround Adherence** | **100% (Strict 1.5h spacing)** | Partial (Overlap risk) | Inflexible / Static | Enforces flight safety & maintenance recovery |
| **Airspace Restriction Respect** | **Hard 0% Violation (Ray-cast)** | Heuristic / Soft | Manual oversight | Eliminates fratricide and boundary breaches |
| **Re-Planning Latency** | **120 ms** | **12 ms** | **Hours / Infeasible** | Real-time dynamic retasking in contested A2/AD |
| **Audited Plan Diff Generation** | **Automated (SHA-256)** | Manual | None | Instant delta situational awareness |

---

## SLIDE 5: SENSITIVITY ANALYSIS (SYSTEM BEHAVIOR UNDER PERTURBATION)
*Demonstrating how the mathematical optimizer adapts to dynamic operational changes.*

### 1. Sensitivity to Pop-Up SAM Threat Radius
| SAM Engagement Radius ($R_{\text{threat}}$) | Route Threat Integral | Selected Route Corridor | Plan Impact / Re-allocation |
|---|:---:|:---:|---|
| **Baseline (30 km)** | 1.82 (Low) | Direct High-Speed Corridor | Su-30MKI assigned Wave-1 strike. |
| **Expanded (60 km)** | 5.40 (Medium) | Lateral Offset Corridors | Trajectory skirts radar envelope; $P(\text{success})$ shifts from 94% $\to$ 88%. |
| **Contested Envelope (90 km)** | **14.20 (Prohibitive)** | **Hard Route Invalidation** | **Solver reroutes through alternate low-risk corridor or reassigns stealth/standoff asset (Rafale with SCALP).** |

### 2. Sensitivity to Bingo Fuel Safety Reserve
| Minimum Bingo Reserve ($F_{\text{reserve}}$) | Feasible Platforms (Radius $\ge D_{\text{RT}}$) | Fuel Margin Left | Plan Impact / Sortie Profile |
|---|:---:|:---:|---|
| **Standard Reserve (800 kg)** | 12 of 12 aircraft | 1,400 kg | All combat sorties cleared for deep strike. |
| **Combat Operational (1,200 kg)** | 10 of 12 aircraft | 950 kg | Enforces realistic safety margin; 2 marginal platforms reassigned to closer CAP. |
| **Adverse Weather / Divert (1,800 kg)** | 6 of 12 aircraft | 320 kg | Distant targets require heavy multirole platforms (Su-30MKI); light fighters held back. |

---

## SLIDE 6: ASSUMPTIONS AND LIMITATIONS
> **Important Advisory Line for Evaluators & Defence Leadership:**
> - **Synthetic Demonstration Data:** All aircraft models, tail numbers, coordinates, intelligence tracks, and maintenance histories are synthetic and unclassified.
> - **Advisory Decision Support Only:** The system is strictly a decision-support and recommender framework; it never executes autonomous weapon releases or unverified flight orders.
> - **Mandatory Human-in-the-Loop Sign-Off:** All initial operational plans and dynamic re-task assignments require explicit human commander approval and four-eyes authorization before operational execution.

---

## SLIDE 7: SUMMARY & COMPETITIVE EDGE
- **100% PS 26250 Native:** Directly solves Air Power dynamic retasking and multi-source operational fusion.
- **Sub-Second Mathematical MILP:** Solves complex multi-wave assignments with turnaround constraints in $<200$ ms.
- **Enterprise-Grade Security:** Hardened with Argon2id, RS256 asymmetric keys, RFC 6238 TOTP MFA, and cryptographic SHA-256 audit trails.
