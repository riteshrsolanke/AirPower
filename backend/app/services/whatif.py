"""
Operational What-If Planning Sandbox Service — Problem Statement 26250.
SIH 2026 | Ministry of Defence | Team $NEXORA$

SYNTHETIC DEMONSTRATION PROTOTYPE ONLY.
Not connected to operational defence systems.

This service executes what-if scenario simulations entirely in-memory.
It does NOT permanently modify the operational database unless explicitly
promoted by an authorised user via promote_simulation_to_plan().
"""
import copy
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from backend.app.models.models import (
    AirBase, Aircraft, AircraftMissionStatus, Crew,
    Mission, MissionPlan, MissionStatus, PlanAssignment, PlanStatus,
    ThreatZone, User, WeaponType, WeatherCondition,
)
from backend.app.services.audit import log_audit
from backend.app.services.optimizer import (
    _load_context,
    solve_operational_scenario,
    AssignmentResult,
    DroppedMission,
)

log = logging.getLogger(__name__)


def get_whatif_options(db: Session) -> Dict[str, Any]:
    """Return available entities to populate the What-If Planning Sandbox UI."""
    aircraft = (
        db.query(Aircraft)
        .order_by(Aircraft.id)
        .all()
    )
    crews = (
        db.query(Crew)
        .order_by(Crew.name)
        .all()
    )
    bases = (
        db.query(AirBase)
        .order_by(AirBase.name)
        .all()
    )
    weapons = (
        db.query(WeaponType)
        .order_by(WeaponType.code)
        .all()
    )
    missions = (
        db.query(Mission)
        .filter(Mission.status == MissionStatus.PENDING)
        .order_by(Mission.priority, Mission.name)
        .all()
    )

    base_name_map = {b.id: b.name for b in bases}

    return {
        "scenarios": [
            {
                "id": "AIRCRAFT_UNAVAILABLE",
                "label": "Aircraft Unavailable (Mechanical/Grounded)",
                "entity_type": "aircraft",
                "description": "Simulate sudden grounding or unserviceability of a specific aircraft.",
            },
            {
                "id": "CREW_UNAVAILABLE",
                "label": "Crew Unavailable (Medical/Fatigued)",
                "entity_type": "crew",
                "description": "Simulate pilot or aircrew member stood down due to fatigue or medical hold.",
            },
            {
                "id": "BASE_UNAVAILABLE",
                "label": "Base / Runway Unavailable (Closure/Damage)",
                "entity_type": "base",
                "description": "Simulate runway closure or operational suspension at an airbase.",
            },
            {
                "id": "WEATHER_RESTRICTION",
                "label": "Weather Restriction (Convective Storm NO-GO)",
                "entity_type": "base",
                "description": "Simulate localized severe meteorological restriction grounding sorties at a base.",
            },
            {
                "id": "RESOURCE_SHORTAGE",
                "label": "Resource / Ordnance Shortage (Depleted Stock)",
                "entity_type": "weapon",
                "description": "Simulate ordnance depletion for a specific weapon type.",
            },
            {
                "id": "NEW_PRIORITY_MISSION",
                "label": "New High-Priority Mission (Emergency Scramble)",
                "entity_type": "custom",
                "description": "Inject an urgent Priority 1 scramble competing for frontline platforms.",
            },
        ],
        "aircraft": [
            {
                "id": a.id,
                "model": a.model,
                "status": a.mission_capable_status.value if a.mission_capable_status else "CAPABLE",
                "base_id": a.base_id,
                "base_name": base_name_map.get(a.base_id, a.location or "Unknown Base"),
                "health_score": a.health_score,
                "rul_hours": a.rul_hours,
                "range_km": getattr(a, "range_km", 2000.0) or 2000.0,
                "payload_capacity": getattr(a, "payload_capacity", 4000.0) or 4000.0,
            }
            for a in aircraft
        ],
        "crews": [
            {
                "id": c.id,
                "name": c.name,
                "rank": c.rank,
                "role": c.role,
                "rest_status": c.rest_status,
                "is_available": c.is_available,
                "base_id": c.base_id,
                "base_name": base_name_map.get(c.base_id, "HQ"),
                "duty_hours_remaining": max(0.0, c.max_duty_hours - c.duty_hours_used),
            }
            for c in crews
        ],
        "bases": [
            {
                "id": b.id,
                "name": b.name,
                "icao_code": b.icao_code,
                "max_capacity": b.max_aircraft_capacity,
                "runway_status": b.runway_status,
            }
            for b in bases
        ],
        "weapons": [
            {
                "code": w.code,
                "name": w.name,
                "category": w.category,
                "range_km": w.range_km,
            }
            for w in weapons
        ],
        "missions": [
            {
                "id": m.id,
                "name": m.name,
                "mission_type": m.mission_type,
                "priority": m.priority,
                "duration_hours": m.estimated_duration_hours,
                "required_aircraft": m.required_aircraft_type,
                "required_weapon": m.required_weapon_code,
            }
            for m in missions
        ],
    }


def run_operational_whatif(
    db: Session,
    scenario_type: str,
    entity_id: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    base_plan_id: Optional[str] = None,
    objective: str = "MAX_COVERAGE",
    current_user: Optional[User] = None,
    ip_address: str = "127.0.0.1",
) -> Dict[str, Any]:
    """
    Execute an in-memory Operational What-If simulation.
    
    1. Loads the base plan to establish baseline assignments.
    2. Modifies in-memory operational state per synthetic scenario.
    3. Executes the multi-objective MILP solver with identical constraints.
    4. Computes comparative plan diff (ADDED, REMOVED, REPLACED, RETAINED).
    5. Audits the action as a simulation (non-persisted).
    """
    parameters = parameters or {}

    # ── Step 1: Baseline Plan ──────────────────────────────────────────────
    base_plan = None
    if base_plan_id:
        base_plan = db.query(MissionPlan).filter(MissionPlan.id == base_plan_id).first()

    if not base_plan:
        # Fetch the latest approved plan or latest proposed plan
        base_plan = (
            db.query(MissionPlan)
            .filter(MissionPlan.status == PlanStatus.APPROVED)
            .order_by(MissionPlan.created_at.desc())
            .first()
        )
        if not base_plan:
            base_plan = (
                db.query(MissionPlan)
                .order_by(MissionPlan.created_at.desc())
                .first()
            )

    # If still no plan exists in DB, generate one first
    if not base_plan:
        from backend.app.services.optimizer import generate_plans
        admin_user_id = current_user.id if current_user else "system"
        fresh_plans = generate_plans(db, created_by_user_id=admin_user_id)
        if fresh_plans:
            base_plan = db.query(MissionPlan).filter(MissionPlan.id == fresh_plans[0].plan_id).first()

    if not base_plan:
        raise RuntimeError("No baseline mission plan could be found or generated.")

    # Load baseline assignments
    base_assignments_raw = (
        db.query(PlanAssignment)
        .filter(PlanAssignment.plan_id == base_plan.id)
        .all()
    )

    from collections import defaultdict
    base_assignments_by_mission: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for ba in base_assignments_raw:
        mission_obj = db.query(Mission).filter(Mission.id == ba.mission_id).first()
        ac_obj = db.query(Aircraft).filter(Aircraft.id == ba.aircraft_id).first() if ba.aircraft_id else None
        crew_obj = db.query(Crew).filter(Crew.id == ba.crew_id).first() if ba.crew_id else None

        base_assignments_by_mission[ba.mission_id].append({
            "mission_id": ba.mission_id,
            "mission_name": mission_obj.name if mission_obj else ba.mission_id,
            "priority": mission_obj.priority if mission_obj else 3,
            "aircraft_id": ba.aircraft_id,
            "aircraft_model": ac_obj.model if ac_obj else None,
            "crew_id": ba.crew_id,
            "crew_name": crew_obj.name if crew_obj else None,
            "threat_exposure_score": ba.threat_exposure_score,
            "explanation": ba.explanation,
        })

    # ── Step 2: In-Memory Context Setup ────────────────────────────────────
    ctx = _load_context(db)
    missions: List[Mission] = list(ctx["missions"])
    aircraft: List[Aircraft] = list(ctx["aircraft"])
    crews: List[Crew] = list(ctx["crews"])
    threats: List[ThreatZone] = list(ctx["threats"])
    weather_map: Dict[str, WeatherCondition] = dict(ctx["weather_map"])
    weapon_inventory: Dict[Tuple[str, str], int] = dict(ctx["weapon_inventory"])
    weapon_compat: Set[Tuple[str, str]] = set(ctx["weapon_compat"])
    wt_by_code: Dict[str, WeaponType] = dict(ctx["wt_by_code"])
    base_capacities: Dict[str, int] = dict(ctx.get("base_capacities", {}))
    base_names: Dict[str, str] = dict(ctx.get("base_names", {}))

    # Reverse lookup for bases
    base_id_by_name = {name.lower(): b_id for b_id, name in base_names.items()}

    scenario_label = scenario_type
    scenario_detail = ""
    constraint_trigger = ""

    # ── Step 3: Apply Synthetic Perturbation ──────────────────────────────
    if scenario_type == "AIRCRAFT_UNAVAILABLE":
        target_ac_id = entity_id or parameters.get("aircraft_id") or "DEMO-A001"
        aircraft = [a for a in aircraft if a.id != target_ac_id]
        scenario_label = f"Aircraft Unavailable: {target_ac_id}"
        scenario_detail = f"Aircraft {target_ac_id} removed from synthetic operational readiness pool."
        constraint_trigger = f"Aircraft {target_ac_id} grounded/unserviceable in scenario."

    elif scenario_type == "CREW_UNAVAILABLE":
        target_crew_id = entity_id or parameters.get("crew_id")
        target_crew_name = parameters.get("crew_name", target_crew_id)
        crews = [c for c in crews if c.id != target_crew_id and c.name != target_crew_id]
        scenario_label = f"Crew Stood Down: {target_crew_name}"
        scenario_detail = f"Crew member {target_crew_name} marked unavailable due to fatigue/medical hold."
        constraint_trigger = f"Crew {target_crew_name} duty hour budget exhausted or rested status withheld."

    elif scenario_type == "BASE_UNAVAILABLE":
        target_base_id = entity_id or parameters.get("base_id")
        # Check if entity_id is name
        if target_base_id and target_base_id.lower() in base_id_by_name:
            target_base_id = base_id_by_name[target_base_id.lower()]
        elif not target_base_id and list(base_names.keys()):
            target_base_id = list(base_names.keys())[0]

        target_base_name = base_names.get(target_base_id, "Selected Base")
        # Filter aircraft out
        aircraft = [a for a in aircraft if getattr(a, "base_id", None) != target_base_id]
        # Set base weather to NO-GO
        if target_base_id in weather_map:
            dummy_wx = copy.copy(weather_map[target_base_id])
            dummy_wx.is_go = False
            dummy_wx.go_no_go_reason = "Synthetic base closure (runway closed)"
            weather_map[target_base_id] = dummy_wx

        scenario_label = f"Base Closure: {target_base_name}"
        scenario_detail = f"Airbase {target_base_name} closed. All stationed platforms excluded from planning."
        constraint_trigger = f"Base capacity set to 0 and runway status CLOSED at {target_base_name}."

    elif scenario_type == "WEATHER_RESTRICTION":
        target_base_id = entity_id or parameters.get("base_id")
        if target_base_id and target_base_id.lower() in base_id_by_name:
            target_base_id = base_id_by_name[target_base_id.lower()]
        elif not target_base_id and list(base_names.keys()):
            target_base_id = list(base_names.keys())[0]

        target_base_name = base_names.get(target_base_id, "Selected Base")
        dummy_wx = WeatherCondition(
            base_id=target_base_id,
            is_go=False,
            go_no_go_reason="Severe convective thunderstorm (visibility < 500m, crosswind > 45 kts)",
            recorded_at=datetime.utcnow(),
        )
        weather_map[target_base_id] = dummy_wx
        scenario_label = f"Weather Restriction: {target_base_name}"
        scenario_detail = f"Adverse weather NO-GO at {target_base_name}."
        constraint_trigger = f"Meteorological minimums not met at {target_base_name}."

    elif scenario_type == "RESOURCE_SHORTAGE":
        weapon_code = entity_id or parameters.get("weapon_code") or "AAM-DEMO-MR"
        # Zero out this weapon across all bases
        for key in list(weapon_inventory.keys()):
            if key[1] == weapon_code:
                weapon_inventory[key] = 0
        scenario_label = f"Resource Depletion: {weapon_code}"
        scenario_detail = f"Inventory for ordnance {weapon_code} depleted to zero across forward stations."
        constraint_trigger = f"Weapon stock shortage: required {weapon_code} not available."

    elif scenario_type == "NEW_PRIORITY_MISSION":
        m_name = parameters.get("name", "SIM-EMERGENCY-SCRAMBLE")
        m_type = parameters.get("mission_type", "DCA")
        req_ac = parameters.get("required_aircraft_type", "DEMO-FIGHTER-Alpha")
        req_wep = parameters.get("required_weapon_code", "AAM-DEMO-MR")
        new_m = Mission(
            id=f"sim-m-{uuid.uuid4().hex[:8]}",
            name=m_name,
            mission_type=m_type,
            priority=1,
            status=MissionStatus.PENDING,
            estimated_duration_hours=float(parameters.get("estimated_duration_hours", 2.0)),
            required_aircraft_type=req_ac,
            required_weapon_code=req_wep,
            min_aircraft_count=int(parameters.get("min_aircraft_count", 1)),
            distance_km=float(parameters.get("distance_km", 450.0)),
            required_payload=float(parameters.get("required_payload", 1800.0)),
            target_area=parameters.get("target_area", {"lat": 29.0, "lon": 76.0, "radius_km": 30.0}),
            notes="Synthetic Priority 1 scramble injected during What-If simulation.",
        )
        missions.insert(0, new_m)
        scenario_label = f"Priority 1 Mission: {m_name}"
        scenario_detail = f"Immediate Priority 1 air mission {m_name} injected into operational tasking queue."
        constraint_trigger = "High-priority resource contention forced dynamic platform reallocation."

    # ── Step 4: Run MILP Optimization In-Memory ───────────────────────────
    objective_mode = objective.upper() if objective else "MAX_COVERAGE"
    if objective_mode not in ["MAX_COVERAGE", "MIN_RISK", "RESOURCE_LEAN"]:
        objective_mode = "MAX_COVERAGE"

    (
        sim_assignments,
        sim_dropped,
        coverage_pct,
        risk_score,
        resource_use,
        solve_ms,
        summary,
    ) = solve_operational_scenario(
        missions=missions,
        aircraft=aircraft,
        crews=crews,
        threats=threats,
        weather_map=weather_map,
        weapon_inventory=weapon_inventory,
        weapon_compat=weapon_compat,
        wt_by_code=wt_by_code,
        base_capacities=base_capacities,
        base_names=base_names,
        airspaces=ctx.get("airspaces", []),
        bases_dict=ctx.get("bases_dict", {}),
        plan_type=objective_mode,
    )

    # ── Step 5: Compute Plan Difference ────────────────────────────────────
    sim_assignments_by_mission: Dict[str, List[AssignmentResult]] = defaultdict(list)
    for a in sim_assignments:
        sim_assignments_by_mission[a.mission_id].append(a)

    all_mission_ids = set(base_assignments_by_mission.keys()) | set(sim_assignments_by_mission.keys())
    diff_records: List[Dict[str, Any]] = []

    added_count = 0
    removed_count = 0
    replaced_count = 0
    retained_count = 0

    for m_id in sorted(all_mission_ids):
        base_items = list(base_assignments_by_mission.get(m_id, []))
        sim_items = list(sim_assignments_by_mission.get(m_id, []))

        # First, match exact retained pairs (same aircraft)
        matched_base_indices = set()
        matched_sim_indices = set()

        for b_idx, b_item in enumerate(base_items):
            for s_idx, s_item in enumerate(sim_items):
                if s_idx in matched_sim_indices:
                    continue
                if b_item["aircraft_id"] == s_item.aircraft_id:
                    matched_base_indices.add(b_idx)
                    matched_sim_indices.add(s_idx)
                    retained_count += 1
                    diff_records.append({
                        "change_type": "RETAINED",
                        "mission_id": m_id,
                        "mission_name": s_item.mission_name,
                        "priority": s_item.priority,
                        "prev_aircraft_id": b_item["aircraft_id"],
                        "new_aircraft_id": s_item.aircraft_id,
                        "prev_crew_id": b_item["crew_id"],
                        "new_crew_id": s_item.crew_id,
                        "note": "Assignment retained without disruption.",
                    })
                    break

        unmatched_base = [b for idx, b in enumerate(base_items) if idx not in matched_base_indices]
        unmatched_sim = [s for idx, s in enumerate(sim_items) if idx not in matched_sim_indices]

        # Next, pair up replacements between unmatched base and unmatched sim
        num_replaced = min(len(unmatched_base), len(unmatched_sim))
        for i in range(num_replaced):
            b_item = unmatched_base[i]
            s_item = unmatched_sim[i]
            replaced_count += 1
            reason_detail = []
            if b_item["aircraft_id"] != s_item.aircraft_id:
                reason_detail.append(
                    f"{b_item['aircraft_id']} replaced by {s_item.aircraft_id} "
                    f"({s_item.aircraft_model}) due to {constraint_trigger or 're-optimisation'}"
                )
            if b_item["crew_id"] != s_item.crew_id:
                reason_detail.append(
                    f"Crew reallocated from {b_item.get('crew_name') or b_item['crew_id']} to {s_item.crew_name or s_item.crew_id}"
                )
            diff_records.append({
                "change_type": "REPLACED",
                "mission_id": m_id,
                "mission_name": s_item.mission_name,
                "priority": s_item.priority,
                "prev_aircraft_id": b_item["aircraft_id"],
                "new_aircraft_id": s_item.aircraft_id,
                "prev_crew_id": b_item["crew_id"],
                "new_crew_id": s_item.crew_id,
                "note": "; ".join(reason_detail) if reason_detail else "Replaced due to re-optimisation",
            })

        # Remaining unmatched base are REMOVED
        for b_item in unmatched_base[num_replaced:]:
            removed_count += 1
            drop_reason = next(
                (d.reason for d in sim_dropped if d.mission_id == m_id),
                constraint_trigger or "Resource constraints in simulated scenario.",
            )
            diff_records.append({
                "change_type": "REMOVED",
                "mission_id": m_id,
                "mission_name": b_item["mission_name"],
                "priority": b_item["priority"],
                "prev_aircraft_id": b_item["aircraft_id"],
                "new_aircraft_id": None,
                "prev_crew_id": b_item["crew_id"],
                "new_crew_id": None,
                "note": f"Mission/sortie dropped in simulated scenario. Reason: {drop_reason}",
            })

        # Remaining unmatched sim are ADDED
        for s_item in unmatched_sim[num_replaced:]:
            added_count += 1
            diff_records.append({
                "change_type": "ADDED",
                "mission_id": m_id,
                "mission_name": s_item.mission_name,
                "priority": s_item.priority,
                "prev_aircraft_id": None,
                "new_aircraft_id": s_item.aircraft_id,
                "prev_crew_id": None,
                "new_crew_id": s_item.crew_id,
                "note": f"Mission/sortie newly scheduled in simulated scenario using {s_item.aircraft_id}.",
            })

    # ── Step 6: Audit Log (Distinguished as SIMULATION) ───────────────────
    user_name = current_user.username if current_user else "anonymous"
    audit_payload = {
        "is_simulation": True,
        "scenario_type": scenario_type,
        "entity_id": entity_id,
        "objective": objective_mode,
        "base_plan_version": base_plan.version,
        "changes": {
            "added": added_count,
            "removed": removed_count,
            "replaced": replaced_count,
            "retained": retained_count,
        },
        "solve_ms": solve_ms,
    }
    log_audit(
        db,
        current_user,
        "WHATIF_SIMULATION_RUN",
        "OPERATIONAL_SANDBOX",
        "SUCCESS",
        ip_address,
        audit_payload,
    )

    # ── Step 7: Impact Summary ─────────────────────────────────────────────
    impact_summary = (
        f"Simulated scenario '{scenario_label}' under {objective_mode}: "
        f"{coverage_pct:.0f}% mission coverage ({resource_use['missions_covered']}/{resource_use['missions_total']}). "
        f"Impact: {replaced_count} sorties replaced, {removed_count} dropped, "
        f"{added_count} added, {retained_count} retained. Solved in {solve_ms} ms."
    )

    sim_id = f"sim-{uuid.uuid4().hex[:12]}"

    return {
        "is_simulation": True,
        "disclaimer": "SIMULATED DECISION SUPPORT — SYNTHETIC DATA. Not permanently committed to database.",
        "scenario": {
            "type": scenario_type,
            "label": scenario_label,
            "entity_id": entity_id,
            "description": scenario_detail,
            "constraint_trigger": constraint_trigger,
            "objective": objective_mode,
        },
        "simulation_id": sim_id,
        "current_plan": {
            "id": base_plan.id,
            "version": base_plan.version,
            "coverage_pct": base_plan.coverage_pct,
            "risk_score": base_plan.risk_score,
            "resource_use": getattr(base_plan, "resource_use", len(base_assignments_raw)),
            "status": base_plan.status.value,
            "assignments_count": len(base_assignments_raw),
        },
        "base_plan": {
            "id": base_plan.id,
            "version": base_plan.version,
            "coverage_pct": base_plan.coverage_pct,
            "risk_score": base_plan.risk_score,
            "resource_use": getattr(base_plan, "resource_use", len(base_assignments_raw)),
            "status": base_plan.status.value,
            "assignments_count": len(base_assignments_raw),
        },
        "simulated_plan": {
            "coverage_pct": coverage_pct,
            "risk_score": risk_score,
            "resource_use": resource_use,
            "objective_score": (
                coverage_pct * 1.5 - risk_score * 12.0
                if objective_mode == "MAX_COVERAGE"
                else (coverage_pct * 1.0 - risk_score * 25.0 if objective_mode == "MIN_RISK" else coverage_pct * 1.0 - risk_score * 8.0 - resource_use * 1.8)
            ),
            "solve_time_ms": solve_ms,
            "summary": summary,
            "assignments": [
                {
                    "mission_id": a.mission_id,
                    "mission_name": a.mission_name,
                    "priority": a.priority,
                    "aircraft_id": a.aircraft_id,
                    "aircraft_model": a.aircraft_model,
                    "crew_id": a.crew_id,
                    "crew_name": a.crew_name,
                    "weapon_code": a.weapon_code,
                    "weapon_quantity": a.weapon_quantity,
                    "threat_exposure_score": a.threat_exposure_score,
                    "explanation": a.explanation,
                }
                for a in sim_assignments
            ],
            "dropped_missions": [
                {
                    "mission_id": d.mission_id,
                    "mission_name": d.mission_name,
                    "priority": d.priority,
                    "reason": d.reason,
                }
                for d in sim_dropped
            ],
        },
        "plan_diff": diff_records,
        "diff_summary": {
            "added": added_count,
            "removed": removed_count,
            "replaced": replaced_count,
            "retained": retained_count,
            "total_changes": added_count + removed_count + replaced_count,
        },
        "impact_summary": impact_summary,
        "feasibility_changes": [
            f"Constraint applied: {constraint_trigger}" if constraint_trigger else "Multi-objective resource redistribution."
        ],
    }


def promote_simulation_to_plan(
    db: Session,
    simulation_result: Dict[str, Any],
    note: str,
    current_user: User,
    ip_address: str = "127.0.0.1",
) -> Dict[str, Any]:
    """
    Explicit user promotion of a simulated What-If plan into a formal PROPOSED plan.
    Requires subsequent approval by a distinct authorized officer (four-eyes rule).
    """
    sim = simulation_result.get("simulated_plan")
    if not sim:
        raise ValueError("Invalid simulation result payload; missing 'simulated_plan'.")

    # Get max version currently in DB
    max_v = db.query(MissionPlan).order_by(MissionPlan.version.desc()).first()
    next_v = (max_v.version + 1) if max_v else 1

    summary_text = (
        f"[PROMOTED FROM WHAT-IF] {sim.get('summary', 'Simulated Plan')} "
        f"(Promoted by {current_user.username}: {note})"
    )

    new_plan = MissionPlan(
        version=next_v,
        status=PlanStatus.PROPOSED,
        coverage_pct=sim.get("coverage_pct", 0.0),
        risk_score=sim.get("risk_score", 0.0),
        resource_use=sim.get("resource_use", {}),
        summary=summary_text,
        created_by=current_user.id,
    )
    db.add(new_plan)
    db.flush()

    for a in sim.get("assignments", []):
        db.add(PlanAssignment(
            plan_id=new_plan.id,
            mission_id=a["mission_id"],
            aircraft_id=a["aircraft_id"],
            crew_id=a.get("crew_id"),
            weapon_type_id=a.get("weapon_type_id"),
            weapon_quantity=a.get("weapon_quantity", 0),
            explanation=a.get("explanation"),
            threat_exposure_score=a.get("threat_exposure_score", 0.0),
        ))

    db.commit()

    log_audit(
        db,
        current_user,
        "PLAN_PROMOTED_FROM_WHATIF",
        new_plan.id,
        "SUCCESS",
        ip_address,
        {
            "promoted_version": next_v,
            "note": note,
            "status": "PROPOSED",
            "four_eyes_required": True,
        },
    )

    return {
        "message": "Simulated plan successfully promoted to formal PROPOSED status.",
        "plan_id": new_plan.id,
        "version": next_v,
        "status": new_plan.status.value,
        "note": "Awaiting second-user four-eyes review and approval.",
    }
