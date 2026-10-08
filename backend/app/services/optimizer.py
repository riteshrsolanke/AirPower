"""
Mission Planning Optimiser — Phase 2.
Problem Statement 26250 | SIH 2026 | Ministry of Defence
ALL DATA IS SYNTHETIC — Not connected to operational defence systems.

Strategy
--------
We use a Mixed-Integer Linear Programme (MILP) via PuLP / CBC to assign
aircraft to missions, then apply greedy post-processing to select crew
and weapons.  Three runs with different objective functions produce three
genuinely distinct plans the user can compare:

  Plan 1 — MAX_COVERAGE   : maximise priority-weighted mission coverage
  Plan 2 — MIN_RISK       : maximise coverage, penalise threat exposure
  Plan 3 — RESOURCE_LEAN  : maximise coverage, penalise aircraft count

Hard constraints (all three plans):
  • Aircraft mission_capable_status != GROUNDED
  • Aircraft RUL >= mission_duration + RUL_SAFETY_MARGIN_HOURS
  • Aircraft model matches mission.required_aircraft_type
  • Required weapon is compatible with aircraft AND in stock at its base
  • Weather at aircraft's base is GO
  • Each aircraft used at most once across all missions
  • Each crew member used at most once

Diversity constraint between plans:
  Plan k+1 must differ from plan k by at least one (mission, aircraft) pair.

Solver time-limit is 4 s per plan; demo scenario (8 missions, ≤14 capable
aircraft) solves well under 1 s per plan.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from pulp import (
    LpBinary, LpProblem, LpMaximize, LpVariable, LpStatus,
    lpSum, value, PULP_CBC_CMD,
)
from sqlalchemy.orm import Session

from backend.app.models.models import (
    Aircraft, AircraftMissionStatus,
    AirBase,
    Crew,
    WeaponType, WeaponInventory, AircraftWeaponCompat,
    Mission, MissionStatus,
    ThreatZone, WeatherCondition,
    MissionPlan, PlanAssignment, PlanStatus,
)

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Aircraft RUL must exceed (mission_duration + this margin) to be eligible
RUL_SAFETY_MARGIN_HOURS: float = 20.0

# Priority 1 = most urgent; weight maps priority → objective coefficient
PRIORITY_WEIGHT: Dict[int, int] = {1: 10, 2: 7, 3: 5, 4: 2, 5: 1}

# Maximum CBC solve time per plan (seconds)
SOLVER_TIME_LIMIT_S: int = 4

# ── Data classes (returned to the API layer) ─────────────────────────────────

@dataclass
class AssignmentResult:
    mission_id: str
    mission_name: str
    mission_type: str
    priority: int
    aircraft_id: str
    aircraft_model: str
    crew_id: Optional[str]
    crew_name: Optional[str]
    weapon_type_id: Optional[str]
    weapon_code: Optional[str]
    weapon_quantity: int
    threat_exposure_score: float
    explanation: str       # plain-language "why chosen"


@dataclass
class DroppedMission:
    mission_id: str
    mission_name: str
    priority: int
    reason: str            # plain-language "why dropped"


@dataclass
class PlanResult:
    plan_id: str
    plan_type: str
    version: int
    coverage_pct: float
    risk_score: float
    resource_use: Dict
    assignments: List[AssignmentResult]
    dropped_missions: List[DroppedMission]
    solve_time_ms: int
    summary: str


# ── Geometry helpers ─────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (km) between two WGS-84 coordinate pairs."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def _threat_exposure(
    target_lat: float,
    target_lon: float,
    threats: List[ThreatZone],
) -> float:
    """
    Compute threat exposure score [0 … 1] for a target point.

    For each active threat zone whose envelope contains the target:
        contribution = (severity / 5) × (1 − dist / radius)
    Contributions are summed and clipped to [0, 1].
    """
    score = 0.0
    for t in threats:
        if not t.is_active:
            continue
        dist = _haversine_km(target_lat, target_lon, t.center_lat, t.center_lon)
        if dist < t.radius_km:
            overlap = 1.0 - dist / t.radius_km       # 0 at edge, 1 at centre
            score += (t.severity / 5.0) * overlap
    return min(1.0, round(score, 4))


# ── Feasibility checks ────────────────────────────────────────────────────────

def _check_aircraft_mission_feasibility(
    aircraft: Aircraft,
    mission: Mission,
    weather_map: Dict[str, WeatherCondition],
    weapon_inventory: Dict[Tuple[str, str], int],   # (base_id, weapon_code) → available qty
    weapon_compat: Set[Tuple[str, str]],             # {(aircraft_id, weapon_code)}
) -> Tuple[bool, List[str]]:
    """
    Return (feasible, [reasons]).
    reasons is empty when feasible; otherwise contains human-readable failure messages.
    """
    reasons: List[str] = []

    # 1. Mission capability
    if aircraft.mission_capable_status == AircraftMissionStatus.GROUNDED:
        reasons.append(
            f"{aircraft.id} is GROUNDED "
            f"(risk={aircraft.failure_risk:.2f}, RUL={aircraft.rul_hours:.0f} h)"
        )

    # 2. Remaining useful life (Use conservative rul_low if available)
    effective_rul = aircraft.rul_hours
    if getattr(aircraft, 'predictions', None):
        latest_pred = sorted(aircraft.predictions, key=lambda x: x.generated_at, reverse=True)[0]
        if latest_pred.rul_low:
            effective_rul = latest_pred.rul_low
        
    required_rul = mission.estimated_duration_hours + RUL_SAFETY_MARGIN_HOURS
    if effective_rul < required_rul:
        reasons.append(
            f"{aircraft.id} RUL(low)={effective_rul:.0f} h < required "
            f"{required_rul:.0f} h "
            f"({mission.estimated_duration_hours:.0f} h mission + "
            f"{RUL_SAFETY_MARGIN_HOURS:.0f} h safety margin)"
        )

    # 3. Aircraft type match
    if mission.required_aircraft_type and aircraft.model != mission.required_aircraft_type:
        reasons.append(
            f"{aircraft.id} is {aircraft.model}; "
            f"mission requires {mission.required_aircraft_type}"
        )

    # 4. Weapon compatibility and stock
    if mission.required_weapon_code:
        if (aircraft.id, mission.required_weapon_code) not in weapon_compat:
            reasons.append(
                f"{aircraft.id} is not cleared to carry {mission.required_weapon_code}"
            )
        else:
            avail = weapon_inventory.get((aircraft.base_id, mission.required_weapon_code), 0)
            if avail < 2:   # require at least 2 rounds per sortie
                reasons.append(
                    f"Insufficient stock of {mission.required_weapon_code} "
                    f"at {aircraft.base_id} (have {avail}, need 2)"
                )

    # 5. Weather go / no-go at base
    if aircraft.base_id:
        wx = weather_map.get(aircraft.base_id)
        if wx and not wx.is_go:
            reasons.append(
                f"Weather NO-GO at {aircraft.base_id}: "
                f"{wx.go_no_go_reason or 'below minimums'}"
            )

    return (len(reasons) == 0), reasons


def _collect_drop_reason(
    m_idx: int,
    missions: List[Mission],
    aircraft: List[Aircraft],
    feasibility: Dict[Tuple[int, int], Tuple[bool, List[str]]],
    was_competed_away: bool,
) -> str:
    """Return a single best-effort reason why a mission could not be assigned."""
    if was_competed_away:
        return (
            "No eligible aircraft remaining — all compatible aircraft "
            "allocated to higher-priority missions."
        )
    # Collect unique infeasibility reasons across all aircraft
    all_reasons: List[str] = []
    for a_idx in range(len(aircraft)):
        ok, rs = feasibility.get((m_idx, a_idx), (False, []))
        if not ok:
            all_reasons.extend(rs)
    # De-duplicate and pick most common / most informative
    unique = list(dict.fromkeys(all_reasons))
    if not unique:
        return "No eligible aircraft: unknown constraint."
    # Prefer type-mismatch and RUL over weather (more actionable)
    for r in unique:
        if "requires" in r or "RUL" in r or "GROUNDED" in r:
            return r
    return unique[0]


# ── Crew selection ────────────────────────────────────────────────────────────

def _pick_crew(
    aircraft: Aircraft,
    mission: Mission,
    crew_pool: List[Crew],
    used_crew_ids: Set[str],
) -> Optional[Crew]:
    """
    Greedy crew selection for a given (aircraft, mission) pair.
    Candidates must be:
      • available and not already used
      • based at the same base as the aircraft
      • qualified for the aircraft model
      • within duty-hour limits
    Preference: RESTED > FATIGUED, then most duty hours remaining.
    """
    candidates: List[Crew] = []
    for c in crew_pool:
        if c.id in used_crew_ids:
            continue
        if not c.is_available:
            continue
        # Co-located check (relaxed: allow if either base is None)
        if c.base_id and aircraft.base_id and c.base_id != aircraft.base_id:
            continue
        # Qualification check
        if aircraft.model not in (c.aircraft_qualifications or []):
            continue
        # Duty-hour budget
        if (c.max_duty_hours - c.duty_hours_used) < mission.estimated_duration_hours:
            continue
        candidates.append(c)

    if not candidates:
        return None

    candidates.sort(
        key=lambda c: (
            0 if c.rest_status == "RESTED" else 1,
            -(c.max_duty_hours - c.duty_hours_used),
        )
    )
    return candidates[0]


# ── Explanation builders ──────────────────────────────────────────────────────

def _explain_assignment(
    mission: Mission,
    ac: Aircraft,
    crew: Optional[Crew],
    weapon_name: Optional[str],
    t_score: float,
    plan_type: str,
) -> str:
    parts: List[str] = []

    # Aircraft rationale
    parts.append(
        f"{ac.id} ({ac.model}) selected: health {ac.health_score:.0f}%, "
        f"RUL {ac.rul_hours:.0f} h "
        f"(≥ {mission.estimated_duration_hours + RUL_SAFETY_MARGIN_HOURS:.0f} h required), "
        f"status {ac.mission_capable_status.value if ac.mission_capable_status else 'CAPABLE'}."
    )

    # Crew rationale
    if crew:
        hrs_left = crew.max_duty_hours - crew.duty_hours_used
        parts.append(
            f"Crew: {crew.name} ({crew.rank}, {crew.role}), "
            f"{hrs_left:.0f} h duty remaining, {crew.rest_status}."
        )
    else:
        parts.append("⚠ No qualified crew found at this base — crew TBA.")

    # Weapon
    if weapon_name:
        parts.append(f"Loaded with {weapon_name} (× 2).")

    # Threat
    if t_score > 0.6:
        label = "HIGH"
    elif t_score > 0.25:
        label = "MODERATE"
    else:
        label = "LOW"
    parts.append(f"Threat exposure: {label} ({t_score:.2f}).")

    # Plan-specific note
    note = {
        "MAX_COVERAGE":   "Chosen to maximise priority-weighted mission coverage.",
        "MIN_RISK":       "Chosen to minimise route exposure to active threat zones.",
        "RESOURCE_LEAN":  "Chosen to deliver coverage with fewest platform sorties.",
    }.get(plan_type, "")
    if note:
        parts.append(note)

    return " ".join(parts)


def _plan_summary(
    plan_type: str,
    coverage_pct: float,
    risk: float,
    ru: Dict,
    dropped: List[DroppedMission],
) -> str:
    label = {
        "MAX_COVERAGE":  "Maximum Coverage",
        "MIN_RISK":      "Minimum Risk",
        "RESOURCE_LEAN": "Resource-Lean",
    }.get(plan_type, plan_type)
    s = (
        f"[{label}] "
        f"{ru['missions_covered']}/{ru['missions_total']} missions covered "
        f"({coverage_pct:.0f}%). "
        f"Threat exposure index: {risk:.3f}. "
        f"Resources: {ru['aircraft_assigned']} aircraft, "
        f"{ru['crews_assigned']} crew."
    )
    if dropped:
        names = ", ".join(d.mission_name for d in dropped[:3])
        extra = "…" if len(dropped) > 3 else ""
        s += f" Dropped: {names}{extra}."
    return s


# ── Core ILP solver ───────────────────────────────────────────────────────────

def _solve_ilp(
    plan_type: str,
    missions: List[Mission],
    aircraft: List[Aircraft],
    feasibility: Dict[Tuple[int, int], Tuple[bool, List[str]]],
    threat_scores: Dict[str, float],
    forbidden_pairs: List[Set[Tuple[str, str]]],  # [(mission_id, aircraft_id), …]
) -> Tuple[Dict[int, List[int]], int, str]:
    """
    Solve one MILP instance.

    Returns:
        assigned  : {m_idx: [a_idx, …]}  — missions that got aircraft
        solve_ms  : wall-clock milliseconds
        lp_status : PuLP status string
    """
    t0 = time.perf_counter()

    nM = len(missions)
    nA = len(aircraft)

    # ── Variables ─────────────────────────────────────────────────────────

    # x[m,a] = 1 iff aircraft a is assigned to mission m
    x: Dict[Tuple[int, int], LpVariable] = {
        (m, a): LpVariable(f"x_{m}_{a}", cat=LpBinary)
        for m in range(nM) for a in range(nA)
    }
    # cov[m] = 1 iff mission m is fully covered
    cov: List[LpVariable] = [
        LpVariable(f"cov_{m}", cat=LpBinary) for m in range(nM)
    ]

    # Pre-compute priority weights and threat score per mission index
    pw = [PRIORITY_WEIGHT.get(missions[m].priority, 1) for m in range(nM)]
    ts = [threat_scores.get(missions[m].id, 0.0) for m in range(nM)]

    # ── Objective ─────────────────────────────────────────────────────────

    prob = LpProblem(f"AirPlan_{plan_type}_{int(time.time())}", LpMaximize)

    coverage_obj = lpSum(pw[m] * cov[m] for m in range(nM))

    if plan_type == "MAX_COVERAGE":
        prob += coverage_obj

    elif plan_type == "MIN_RISK":
        # Coverage is primary; threat exposure is a penalty
        risk_penalty = lpSum(
            ts[m] * lpSum(x[m, a] for a in range(nA))
            for m in range(nM)
        )
        prob += coverage_obj - 2.5 * risk_penalty

    elif plan_type == "RESOURCE_LEAN":
        # Coverage is primary; penalise total aircraft sorties
        sorties = lpSum(x[m, a] for m in range(nM) for a in range(nA))
        prob += coverage_obj - 0.15 * sorties

    else:
        prob += coverage_obj   # fallback

    # ── Constraints ───────────────────────────────────────────────────────

    for m in range(nM):
        min_k = missions[m].min_aircraft_count

        # Count feasible aircraft for this mission
        feasible_a = [
            a for a in range(nA) if feasibility.get((m, a), (False, []))[0]
        ]

        # Infeasible pairs forced to 0
        for a in range(nA):
            if a not in feasible_a:
                prob += x[m, a] == 0, f"infeas_{m}_{a}"

        # Coverage linkage: sum == min_k * cov[m]  (exact fit)
        prob += (
            lpSum(x[m, a] for a in range(nA)) == min_k * cov[m],
            f"cov_link_{m}",
        )

        # Cannot be covered if not enough feasible aircraft exist
        if len(feasible_a) < min_k:
            prob += cov[m] == 0, f"infeas_mission_{m}"

    # Each aircraft used at most once (across all missions)
    for a in range(nA):
        prob += (
            lpSum(x[m, a] for m in range(nM)) <= 1,
            f"ac_once_{a}",
        )

    # Diversity: plan k+1 must differ from every previous plan by ≥ 1 pair
    m_ids = [missions[m].id for m in range(nM)]
    a_ids = [aircraft[a].id for a in range(nA)]
    for fp_idx, forbidden_set in enumerate(forbidden_pairs):
        matching_vars = [
            x[m, a]
            for m in range(nM)
            for a in range(nA)
            if (m_ids[m], a_ids[a]) in forbidden_set
        ]
        if matching_vars:
            prob += (
                lpSum(matching_vars) <= len(matching_vars) - 1,
                f"diversity_{fp_idx}",
            )

    # ── Solve ─────────────────────────────────────────────────────────────

    solver = PULP_CBC_CMD(msg=False, timeLimit=SOLVER_TIME_LIMIT_S)
    prob.solve(solver)

    solve_ms = int((time.perf_counter() - t0) * 1000)
    status_str = LpStatus.get(prob.status, "Unknown")

    assigned: Dict[int, List[int]] = {}
    if prob.status == 1:   # Optimal (or feasible within time limit)
        for m in range(nM):
            if (v := value(cov[m])) is not None and v > 0.5:
                acs = [a for a in range(nA) if (v2 := value(x[m, a])) is not None and v2 > 0.5]
                if acs:
                    assigned[m] = acs

    log.debug(
        "ILP %s: status=%s assignments=%d solve_ms=%d",
        plan_type, status_str, len(assigned), solve_ms,
    )
    return assigned, solve_ms, status_str


from backend.app.services.fatigue import compute_fatigue_score
from datetime import datetime

# ── Context loader ────────────────────────────────────────────────────────────

def _load_context(db: Session) -> Dict:
    """
    Load all planning data from the database into memory.
    Called once per generate_plans() invocation.
    """
    aircraft = (
        db.query(Aircraft)
        .filter(Aircraft.mission_capable_status != AircraftMissionStatus.GROUNDED)
        .all()
    )

    raw_crews = db.query(Crew).filter(Crew.is_available.is_(True)).all()
    crews = []
    now = datetime.utcnow()
    for c in raw_crews:
        fatigue = compute_fatigue_score(c.duty_logs, current_time=now)
        if fatigue["status"] == "UNFIT":
            has_override = any(o for o in c.overrides if o.status == "APPROVED" and o.expires_at > now)
            if not has_override:
                continue
        crews.append(c)

    missions = (
        db.query(Mission)
        .filter(Mission.status == MissionStatus.PENDING)
        .order_by(Mission.priority, Mission.name)
        .all()
    )

    threats = db.query(ThreatZone).filter(ThreatZone.is_active.is_(True)).all()

    # Weather: best (most recent) record per base
    weather_map: Dict[str, WeatherCondition] = {}
    for wx in db.query(WeatherCondition).all():
        if wx.base_id:
            prev = weather_map.get(wx.base_id)
            if prev is None or wx.recorded_at > prev.recorded_at:
                weather_map[wx.base_id] = wx

    # Weapon inventory map: (base_id, weapon_code) → available quantity
    wt_by_id: Dict[str, WeaponType] = {w.id: w for w in db.query(WeaponType).all()}
    weapon_inventory: Dict[Tuple[str, str], int] = {}
    for inv in db.query(WeaponInventory).all():
        wt = wt_by_id.get(inv.weapon_type_id)
        if wt:
            key = (inv.base_id, wt.code)
            weapon_inventory[key] = max(0, inv.quantity - inv.reserved_quantity)

    # Weapon compatibility: set of (aircraft_id, weapon_code)
    weapon_compat: Set[Tuple[str, str]] = set()
    for compat in db.query(AircraftWeaponCompat).all():
        wt = wt_by_id.get(compat.weapon_type_id)
        if wt:
            weapon_compat.add((compat.aircraft_id, wt.code))

    # Weapon lookup by code
    wt_by_code: Dict[str, WeaponType] = {w.code: w for w in wt_by_id.values()}

    return {
        "aircraft":         aircraft,
        "crews":            crews,
        "missions":         missions,
        "threats":          threats,
        "weather_map":      weather_map,
        "weapon_inventory": weapon_inventory,
        "weapon_compat":    weapon_compat,
        "wt_by_code":       wt_by_code,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def generate_plans(db: Session, created_by_user_id: str) -> List[PlanResult]:
    """
    Generate and persist 3 mission plans (MAX_COVERAGE, MIN_RISK, RESOURCE_LEAN).

    Returns a list of PlanResult dataclasses (already saved to DB).
    Raises RuntimeError if no pending missions exist.
    """
    t_global = time.perf_counter()
    log.info("generate_plans() start  user=%s", created_by_user_id)

    ctx = _load_context(db)
    missions  = ctx["missions"]
    aircraft  = ctx["aircraft"]
    crews     = ctx["crews"]
    threats   = ctx["threats"]
    weather_map      = ctx["weather_map"]
    weapon_inventory = ctx["weapon_inventory"]
    weapon_compat    = ctx["weapon_compat"]
    wt_by_code       = ctx["wt_by_code"]

    if not missions:
        raise RuntimeError("No PENDING missions found. Seed missions before planning.")

    # ── Pre-compute feasibility matrix ────────────────────────────────────

    feasibility: Dict[Tuple[int, int], Tuple[bool, List[str]]] = {}
    for m_idx, mission in enumerate(missions):
        for a_idx, ac in enumerate(aircraft):
            ok, reasons = _check_aircraft_mission_feasibility(
                ac, mission, weather_map, weapon_inventory, weapon_compat
            )
            feasibility[m_idx, a_idx] = (ok, reasons)

    # ── Pre-compute threat scores ─────────────────────────────────────────

    threat_scores: Dict[str, float] = {}
    for mission in missions:
        ta = mission.target_area or {}
        lat, lon = ta.get("lat", 0.0), ta.get("lon", 0.0)
        threat_scores[mission.id] = _threat_exposure(lat, lon, threats)

    # ── Solve three plans ─────────────────────────────────────────────────

    plan_types = ["MAX_COVERAGE", "MIN_RISK", "RESOURCE_LEAN"]
    plan_results: List[PlanResult] = []
    forbidden_pairs: List[Set[Tuple[str, str]]] = []

    for version, plan_type in enumerate(plan_types, start=1):
        log.info("Solving plan %d/%d: %s", version, len(plan_types), plan_type)

        assigned, solve_ms, lp_status = _solve_ilp(
            plan_type=plan_type,
            missions=missions,
            aircraft=aircraft,
            feasibility=feasibility,
            threat_scores=threat_scores,
            forbidden_pairs=forbidden_pairs,
        )

        # ── Post-process: crew + weapon selection ─────────────────────────

        used_crew_ids: Set[str]                         = set()
        used_weapon_counts: Dict[Tuple[str, str], int]  = dict(weapon_inventory)
        current_forbidden: Set[Tuple[str, str]]         = set()

        assignment_results: List[AssignmentResult] = []

        for m_idx in sorted(assigned, key=lambda i: missions[i].priority):
            mission = missions[m_idx]
            for a_idx in assigned[m_idx]:
                ac = aircraft[a_idx]
                current_forbidden.add((mission.id, ac.id))

                # Crew
                crew = _pick_crew(ac, mission, crews, used_crew_ids)
                if crew:
                    used_crew_ids.add(crew.id)

                # Weapon
                wt_obj: Optional[WeaponType] = None
                wt_qty = 0
                if mission.required_weapon_code:
                    wt_obj = wt_by_code.get(mission.required_weapon_code)
                    if wt_obj:
                        inv_key = (ac.base_id, mission.required_weapon_code)
                        available = used_weapon_counts.get(inv_key, 0)
                        if available >= 2:
                            wt_qty = 2
                            used_weapon_counts[inv_key] = available - wt_qty

                t_score = threat_scores.get(mission.id, 0.0)

                assignment_results.append(AssignmentResult(
                    mission_id=mission.id,
                    mission_name=mission.name,
                    mission_type=mission.mission_type,
                    priority=mission.priority,
                    aircraft_id=ac.id,
                    aircraft_model=ac.model,
                    crew_id=crew.id if crew else None,
                    crew_name=crew.name if crew else None,
                    weapon_type_id=wt_obj.id if wt_obj else None,
                    weapon_code=wt_obj.code if wt_obj else None,
                    weapon_quantity=wt_qty,
                    threat_exposure_score=round(t_score, 4),
                    explanation=_explain_assignment(
                        mission, ac, crew,
                        wt_obj.name if wt_obj else None,
                        t_score, plan_type,
                    ),
                ))

        # ── Dropped missions ──────────────────────────────────────────────

        dropped: List[DroppedMission] = []
        for m_idx, mission in enumerate(missions):
            if m_idx not in assigned:
                competed_away = all(
                    feasibility.get((m_idx, a_idx), (False, []))[0]
                    for a_idx in range(len(aircraft))
                ) if aircraft else False
                # Was it structurally infeasible or just outcompeted?
                any_feasible = any(
                    feasibility.get((m_idx, a_idx), (False, []))[0]
                    for a_idx in range(len(aircraft))
                )
                dropped.append(DroppedMission(
                    mission_id=mission.id,
                    mission_name=mission.name,
                    priority=mission.priority,
                    reason=_collect_drop_reason(
                        m_idx, missions, aircraft, feasibility,
                        was_competed_away=any_feasible,
                    ),
                ))

        # ── Metrics ───────────────────────────────────────────────────────

        n_covered = len(assigned)
        coverage_pct = round((n_covered / len(missions)) * 100, 1) if missions else 0.0

        risk_score = (
            round(
                sum(a.threat_exposure_score for a in assignment_results)
                / len(assignment_results),
                4,
            )
            if assignment_results else 0.0
        )

        resource_use = {
            "aircraft_assigned": len({a.aircraft_id for a in assignment_results}),
            "crews_assigned":    len({a.crew_id for a in assignment_results if a.crew_id}),
            "missions_covered":  n_covered,
            "missions_total":    len(missions),
            "missions_dropped":  len(dropped),
            "lp_status":         lp_status,
            "solve_time_ms":     solve_ms,
        }

        summary = _plan_summary(plan_type, coverage_pct, risk_score, resource_use, dropped)

        # ── Persist to database ───────────────────────────────────────────

        plan_db = MissionPlan(
            version=version,
            status=PlanStatus.PROPOSED,
            coverage_pct=coverage_pct,
            risk_score=risk_score,
            resource_use=resource_use,
            summary=summary,
            created_by=created_by_user_id,
        )
        db.add(plan_db)
        db.flush()   # obtain plan_db.id before inserting assignments

        for ar in assignment_results:
            db.add(PlanAssignment(
                plan_id=plan_db.id,
                mission_id=ar.mission_id,
                aircraft_id=ar.aircraft_id,
                crew_id=ar.crew_id,
                weapon_type_id=ar.weapon_type_id,
                weapon_quantity=ar.weapon_quantity,
                explanation=ar.explanation,
                threat_exposure_score=ar.threat_exposure_score,
            ))

        db.commit()

        # Forbid this plan's exact assignment set for the next iteration
        forbidden_pairs.append(current_forbidden)

        plan_results.append(PlanResult(
            plan_id=plan_db.id,
            plan_type=plan_type,
            version=version,
            coverage_pct=coverage_pct,
            risk_score=risk_score,
            resource_use=resource_use,
            assignments=assignment_results,
            dropped_missions=dropped,
            solve_time_ms=solve_ms,
            summary=summary,
        ))

        log.info(
            "Plan %s saved: id=%s coverage=%.0f%% risk=%.3f solve_ms=%d",
            plan_type, plan_db.id, coverage_pct, risk_score, solve_ms,
        )

    total_ms = int((time.perf_counter() - t_global) * 1000)
    log.info("generate_plans() done: %d plans, total %d ms", len(plan_results), total_ms)
    return plan_results


def get_plan(db: Session, plan_id: str) -> Optional[Dict]:
    """
    Fetch a persisted plan (with all assignments) and return as a dict.
    Returns None if not found.
    """
    plan = db.query(MissionPlan).filter(MissionPlan.id == plan_id).first()
    if not plan:
        return None

    assignments = []
    for pa in plan.assignments:
        # Resolve names for display
        mission = db.query(Mission).filter(Mission.id == pa.mission_id).first()
        ac = db.query(Aircraft).filter(Aircraft.id == pa.aircraft_id).first() if pa.aircraft_id else None
        crew = db.query(Crew).filter(Crew.id == pa.crew_id).first() if pa.crew_id else None
        wt = db.query(WeaponType).filter(WeaponType.id == pa.weapon_type_id).first() if pa.weapon_type_id else None

        assignments.append({
            "id": pa.id,
            "mission_id": pa.mission_id,
            "mission_name": mission.name if mission else None,
            "mission_type": mission.mission_type if mission else None,
            "priority": mission.priority if mission else None,
            "aircraft_id": pa.aircraft_id,
            "aircraft_model": ac.model if ac else None,
            "crew_id": pa.crew_id,
            "crew_name": crew.name if crew else None,
            "weapon_code": wt.code if wt else None,
            "weapon_quantity": pa.weapon_quantity,
            "threat_exposure_score": pa.threat_exposure_score,
            "explanation": pa.explanation,
        })

    return {
        "id": plan.id,
        "version": plan.version,
        "status": plan.status.value,
        "coverage_pct": plan.coverage_pct,
        "risk_score": plan.risk_score,
        "resource_use": plan.resource_use,
        "summary": plan.summary,
        "created_at": plan.created_at.isoformat(),
        "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
        "approved_by": plan.approved_by,
        "rejected_at": plan.rejected_at.isoformat() if plan.rejected_at else None,
        "rejection_reason": plan.rejection_reason,
        "assignments": assignments,
    }


# ── Phase 3: Incremental retasking ────────────────────────────────────────────

def retask_missions(
    db: Session,
    mission_ids: List[str],          # missions to (re-)plan
    locked_aircraft_ids: Set[str],   # aircraft committed to unaffected missions
    locked_crew_ids: Set[str],        # crew committed to unaffected missions
    trigger_event_id: str,
    created_by_user_id: str,
    base_plan_version: int,
    plan_type: str = "MAX_COVERAGE",
) -> Optional[PlanResult]:
    """
    Run the optimiser over a constrained resource pool to generate one
    incremental retask plan.

    Used by the retasker service after an event changes the operational
    picture.  Only the missions in `mission_ids` are replanned; aircraft /
    crew in the locked sets are treated as unavailable.

    Returns None if no pending missions remain or all are infeasible.
    All data is synthetic.
    """
    ctx = _load_context(db)

    # Filter: only the missions we need to replan
    all_missions = ctx["missions"]
    missions = [m for m in all_missions if m.id in set(mission_ids)]

    # Add any PENDING missions not already in the set (newly added missions)
    extra_pending = [m for m in all_missions if m.id not in set(mission_ids)]
    # Include extra pending only if this is a fresh retask (not just fixups)
    # For simplicity, just replan the specified missions
    if not missions:
        log.info("retask_missions: no matching PENDING missions for %s", mission_ids)
        return None

    # Filter: aircraft not locked, not GROUNDED
    aircraft = [
        ac for ac in ctx["aircraft"]
        if ac.id not in locked_aircraft_ids
    ]

    crews = [
        c for c in ctx["crews"]
        if c.id not in locked_crew_ids
    ]

    if not aircraft:
        log.warning("retask_missions: no available aircraft (all locked or grounded)")
        return None

    # Pre-compute feasibility for this reduced resource pool
    feasibility: Dict[Tuple[int, int], Tuple[bool, List[str]]] = {}
    for m_idx, mission in enumerate(missions):
        for a_idx, ac in enumerate(aircraft):
            ok, reasons = _check_aircraft_mission_feasibility(
                ac, mission,
                ctx["weather_map"],
                ctx["weapon_inventory"],
                ctx["weapon_compat"],
            )
            feasibility[m_idx, a_idx] = (ok, reasons)

    threats = ctx["threats"]
    threat_scores = {
        m.id: _threat_exposure(
            (m.target_area or {}).get("lat", 0.0),
            (m.target_area or {}).get("lon", 0.0),
            threats,
        )
        for m in missions
    }

    assigned, solve_ms, lp_status = _solve_ilp(
        plan_type=plan_type,
        missions=missions,
        aircraft=aircraft,
        feasibility=feasibility,
        threat_scores=threat_scores,
        forbidden_pairs=[],   # no diversity constraint for retask
    )

    # Post-process
    used_crew_ids: Set[str] = set(locked_crew_ids)  # start from already-used
    used_weapon_counts = dict(ctx["weapon_inventory"])
    assignment_results: List[AssignmentResult] = []

    for m_idx in sorted(assigned, key=lambda i: missions[i].priority):
        mission = missions[m_idx]
        for a_idx in assigned[m_idx]:
            ac = aircraft[a_idx]
            crew = _pick_crew(ac, mission, crews, used_crew_ids)
            if crew:
                used_crew_ids.add(crew.id)

            wt_obj: Optional[WeaponType] = None
            wt_qty = 0
            if mission.required_weapon_code:
                wt_obj = ctx["wt_by_code"].get(mission.required_weapon_code)
                if wt_obj:
                    inv_key = (ac.base_id, mission.required_weapon_code)
                    if used_weapon_counts.get(inv_key, 0) >= 2:
                        wt_qty = 2
                        used_weapon_counts[inv_key] -= 2

            t_score = threat_scores.get(mission.id, 0.0)
            assignment_results.append(AssignmentResult(
                mission_id=mission.id,
                mission_name=mission.name,
                mission_type=mission.mission_type,
                priority=mission.priority,
                aircraft_id=ac.id,
                aircraft_model=ac.model,
                crew_id=crew.id if crew else None,
                crew_name=crew.name if crew else None,
                weapon_type_id=wt_obj.id if wt_obj else None,
                weapon_code=wt_obj.code if wt_obj else None,
                weapon_quantity=wt_qty,
                threat_exposure_score=round(t_score, 4),
                explanation=_explain_assignment(
                    mission, ac, crew,
                    wt_obj.name if wt_obj else None,
                    t_score, plan_type,
                ) + " [RETASK — triggered by operational event]",
            ))

    dropped: List[DroppedMission] = []
    for m_idx, mission in enumerate(missions):
        if m_idx not in assigned:
            any_feasible = any(
                feasibility.get((m_idx, a_idx), (False, []))[0]
                for a_idx in range(len(aircraft))
            )
            dropped.append(DroppedMission(
                mission_id=mission.id,
                mission_name=mission.name,
                priority=mission.priority,
                reason=_collect_drop_reason(
                    m_idx, missions, aircraft, feasibility,
                    was_competed_away=any_feasible,
                ),
            ))

    n_covered = len(assigned)
    coverage_pct = round((n_covered / len(missions)) * 100, 1) if missions else 0.0
    risk_score = (
        round(sum(a.threat_exposure_score for a in assignment_results) / len(assignment_results), 4)
        if assignment_results else 0.0
    )
    resource_use = {
        "aircraft_assigned": len({a.aircraft_id for a in assignment_results}),
        "crews_assigned":    len({a.crew_id for a in assignment_results if a.crew_id}),
        "missions_covered":  n_covered,
        "missions_total":    len(missions),
        "missions_dropped":  len(dropped),
        "lp_status":         lp_status,
        "solve_time_ms":     solve_ms,
        "retask": True,
    }

    summary = (
        f"[RETASK v{base_plan_version + 1}] {n_covered}/{len(missions)} affected missions replanned "
        f"({coverage_pct:.0f}%). Threat index: {risk_score:.3f}. "
        f"Resources: {resource_use['aircraft_assigned']} aircraft."
    )
    if dropped:
        summary += f" Could not replan: {', '.join(d.mission_name for d in dropped[:2])}."

    # Persist
    plan_db = MissionPlan(
        version=base_plan_version + 1,
        status=PlanStatus.PROPOSED,
        coverage_pct=coverage_pct,
        risk_score=risk_score,
        resource_use=resource_use,
        summary=summary,
        created_by=created_by_user_id,
        trigger_event_id=trigger_event_id,
    )
    db.add(plan_db)
    db.flush()

    for ar in assignment_results:
        db.add(PlanAssignment(
            plan_id=plan_db.id,
            mission_id=ar.mission_id,
            aircraft_id=ar.aircraft_id,
            crew_id=ar.crew_id,
            weapon_type_id=ar.weapon_type_id,
            weapon_quantity=ar.weapon_quantity,
            explanation=ar.explanation,
            threat_exposure_score=ar.threat_exposure_score,
        ))

    db.commit()

    log.info(
        "retask_missions done: plan=%s v=%d coverage=%.0f%% solve_ms=%d",
        plan_db.id, base_plan_version + 1, coverage_pct, solve_ms,
    )

    return PlanResult(
        plan_id=plan_db.id,
        plan_type=f"RETASK_{plan_type}",
        version=base_plan_version + 1,
        coverage_pct=coverage_pct,
        risk_score=risk_score,
        resource_use=resource_use,
        assignments=assignment_results,
        dropped_missions=dropped,
        solve_time_ms=solve_ms,
        summary=summary,
    )
