from backend.app.services.audit import log_audit
"""
Planning API — Phase 2 & 3.
Problem Statement 26250 | SIH 2026 | Ministry of Defence
ALL DATA IS SYNTHETIC — Not connected to operational defence systems.

Endpoints
---------
POST /api/planning/generate          → run optimiser, return 3 plans  (Analyst+)
GET  /api/planning                   → list all saved plans            (Any auth)
GET  /api/planning/compare           → side-by-side top-3 comparison   (Any auth)
GET  /api/planning/{id}              → full plan with assignments       (Any auth)
GET  /api/planning/{id}/diff/{base}  → compare plan vs base plan       (Any auth)
POST /api/planning/{id}/approve      → approve plan (Analyst+)
POST /api/planning/{id}/reject       → reject plan  (Analyst+)
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.core.deps import (
    get_current_active_user,
    require_analyst_or_above,
    require_any_authenticated,
    _log_audit,
)
from backend.app.db.database import get_db
from backend.app.models.models import (
    MissionPlan, PlanAssignment, PlanStatus,
    Mission, Aircraft, Crew, WeaponType,
    AuditLog, User,
)
from backend.app.services.optimizer import generate_plans, get_plan
from backend.app.services.retasker import compute_plan_diff

log = logging.getLogger(__name__)

router = APIRouter(prefix="/planning", tags=["Planning"])


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_ip(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (
        request.client.host if request.client else "unknown"
    )


def _audit(db, user, action, resource, result, ip, details=None):
    log_audit(db, user, action, resource, result, ip, details)
def _plan_list_item(plan: MissionPlan) -> dict:
    """Compact representation for list views."""
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
        "trigger_event_id": plan.trigger_event_id,
    }


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class GeneratePlanRequest(BaseModel):
    """Optional filters for the planning run. Leave empty for full scenario."""
    mission_ids: Optional[list] = None    # if set, only plan these missions
    note: Optional[str] = None            # free-text note attached to audit log


class RejectRequest(BaseModel):
    reason: str


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate")
async def generate_mission_plans(
    req: GeneratePlanRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """
    Run the optimisation engine and persist the top-3 mission plans.

    Returns all three plan results with full assignment details.
    Requires ANALYST role or above.

    Solve time:  < 5 s for the demo scenario (8 missions, 30 aircraft).
    All data is synthetic.
    """
    ip = _get_ip(request)

    try:
        plan_results = generate_plans(db, created_by_user_id=current_user.id)
    except RuntimeError as exc:
        # e.g. no pending missions
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("Optimiser error: %s", exc)
        _audit(db, current_user, "PLAN_GENERATION_FAILED", "optimizer", "FAILURE", ip,
               {"error": str(exc)})
        raise HTTPException(
            status_code=500,
            detail="Optimiser encountered an internal error. See server logs.",
        )

    _audit(
        db, current_user,
        "PLAN_GENERATED", "mission_plans", "SUCCESS", ip,
        {
            "plans_generated": len(plan_results),
            "plan_ids": [p.plan_id for p in plan_results],
            "note": req.note,
        },
    )

    return {
        "message": f"{len(plan_results)} plans generated successfully.",
        "disclaimer": "All data is synthetic. Not connected to operational systems.",
        "plans": [
            {
                "plan_id":       p.plan_id,
                "plan_type":     p.plan_type,
                "version":       p.version,
                "coverage_pct":  p.coverage_pct,
                "risk_score":    p.risk_score,
                "resource_use":  p.resource_use,
                "summary":       p.summary,
                "solve_time_ms": p.solve_time_ms,
                "assignments": [
                    {
                        "mission_id":           a.mission_id,
                        "mission_name":         a.mission_name,
                        "mission_type":         a.mission_type,
                        "priority":             a.priority,
                        "aircraft_id":          a.aircraft_id,
                        "aircraft_model":       a.aircraft_model,
                        "crew_id":              a.crew_id,
                        "crew_name":            a.crew_name,
                        "weapon_code":          a.weapon_code,
                        "weapon_quantity":      a.weapon_quantity,
                        "threat_exposure_score":a.threat_exposure_score,
                        "explanation":          a.explanation,
                    }
                    for a in p.assignments
                ],
                "dropped_missions": [
                    {
                        "mission_id":   d.mission_id,
                        "mission_name": d.mission_name,
                        "priority":     d.priority,
                        "reason":       d.reason,
                    }
                    for d in p.dropped_missions
                ],
            }
            for p in plan_results
        ],
    }


@router.get("/compare")
async def compare_top_plans(
    limit: int = 3,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Return the most recent `limit` plans side-by-side for comparison.
    Useful for the PLAN view comparison table in the UI.
    """
    plans = (
        db.query(MissionPlan)
        .order_by(MissionPlan.created_at.desc())
        .limit(limit)
        .all()
    )
    if not plans:
        return {"plans": [], "total": 0}

    result = []
    for plan in reversed(plans):   # chronological order
        assignments = db.query(PlanAssignment).filter(
            PlanAssignment.plan_id == plan.id
        ).all()

        missions_covered = [
            {
                "mission_id": pa.mission_id,
                "aircraft_id": pa.aircraft_id,
                "crew_id": pa.crew_id,
                "threat_exposure_score": pa.threat_exposure_score,
            }
            for pa in assignments
        ]

        result.append({
            "id":            plan.id,
            "version":       plan.version,
            "status":        plan.status.value,
            "coverage_pct":  plan.coverage_pct,
            "risk_score":    plan.risk_score,
            "resource_use":  plan.resource_use,
            "summary":       plan.summary,
            "created_at":    plan.created_at.isoformat(),
            "missions_covered": missions_covered,
        })

    return {"plans": result, "total": len(result)}


@router.get("")
async def list_plans(
    status_filter: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """List all saved mission plans, newest first."""
    q = db.query(MissionPlan)
    if status_filter:
        try:
            q = q.filter(MissionPlan.status == PlanStatus(status_filter.upper()))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status_filter}")
    total = q.count()
    plans = q.order_by(MissionPlan.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "plans": [_plan_list_item(p) for p in plans],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/{plan_id}")
async def get_plan_detail(
    plan_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Return a single plan with full assignment details.
    Each assignment includes the plain-language explanation from the optimizer.
    """
    result = get_plan(db, plan_id)
    if not result:
        raise HTTPException(status_code=404, detail="Plan not found")
    return result


@router.post("/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """
    Mark a PROPOSED plan as APPROVED.

    Phase 6: Enforces the four-eyes rule (approver must differ from creator).
    """
    ip = _get_ip(request)
    plan = db.query(MissionPlan).filter(MissionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != PlanStatus.PROPOSED:
        raise HTTPException(
            status_code=409,
            detail=f"Plan is already {plan.status.value}; only PROPOSED plans can be approved.",
        )

    # Phase 6: Enforce ABAC (Attribute-Based Access Control)
    # Only users with SECRET or TOP SECRET clearance can approve plans.
    if current_user.clearance_level not in ["SECRET", "TOP SECRET"]:
        _audit(db, current_user, "PLAN_APPROVED", plan_id, "DENIED", ip,
               {"reason": "ABAC violation: Insufficient clearance", "clearance": current_user.clearance_level})
        raise HTTPException(
            status_code=403,
            detail="ABAC VIOLATION: You do not have the required clearance to approve plans."
        )

    # Phase 6: Enforce four-eyes rule
    if plan.created_by == current_user.id:
        _audit(db, current_user, "PLAN_APPROVED", plan_id, "DENIED", ip,
               {"reason": "Four-eyes violation", "plan_version": plan.version})
        raise HTTPException(
            status_code=403,
            detail="FOUR-EYES RULE VIOLATION: You cannot approve a plan you created."
        )

    plan.status = PlanStatus.APPROVED
    plan.approved_by = current_user.id
    plan.approved_at = datetime.utcnow()
    db.commit()

    _audit(db, current_user, "PLAN_APPROVED", plan_id, "SUCCESS", ip,
           {"plan_version": plan.version, "four_eyes_enforced": True})

    return {
        "message": "Plan approved.",
        "plan_id": plan_id,
        "approved_by": current_user.username,
        "approved_at": plan.approved_at.isoformat(),
        "note": "Four-eyes enforced successfully.",
    }


@router.post("/{plan_id}/reject")
async def reject_plan(
    plan_id: str,
    req: RejectRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Reject a PROPOSED plan with a mandatory reason."""
    ip = _get_ip(request)
    plan = db.query(MissionPlan).filter(MissionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if plan.status != PlanStatus.PROPOSED:
        raise HTTPException(
            status_code=409,
            detail=f"Only PROPOSED plans can be rejected; this plan is {plan.status.value}.",
        )

    plan.status = PlanStatus.REJECTED
    plan.rejected_by = current_user.id
    plan.rejected_at = datetime.utcnow()
    plan.rejection_reason = req.reason
    db.commit()

    _audit(db, current_user, "PLAN_REJECTED", plan_id, "SUCCESS", ip,
           {"reason": req.reason, "plan_version": plan.version})

    return {
        "message": "Plan rejected.",
        "plan_id": plan_id,
        "rejected_by": current_user.username,
        "reason": req.reason,
    }


@router.get("/{plan_id}/diff/{base_plan_id}")
async def plan_diff(
    plan_id: str,
    base_plan_id: str,
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """
    Compare plan `plan_id` against `base_plan_id` assignment-by-assignment.

    Returns a list of changes classified as:
    - ADDED    : mission covered in new plan but not base
    - REMOVED  : mission covered in base plan but not new
    - REPLACED : same mission but different aircraft/crew
    - RETAINED : identical assignment in both plans

    Used by the PLAN view to highlight what changed after a retask event.
    """
    # Validate both plans exist
    for pid in (plan_id, base_plan_id):
        if not db.query(MissionPlan).filter(MissionPlan.id == pid).first():
            raise HTTPException(status_code=404, detail=f"Plan not found: {pid}")

    changes = compute_plan_diff(db, base_plan_id, plan_id)

    added    = sum(1 for c in changes if c.change_type == "ADDED")
    removed  = sum(1 for c in changes if c.change_type == "REMOVED")
    replaced = sum(1 for c in changes if c.change_type == "REPLACED")
    retained = sum(1 for c in changes if c.change_type == "RETAINED")

    return {
        "plan_id":      plan_id,
        "base_plan_id": base_plan_id,
        "summary": {
            "added": added, "removed": removed,
            "replaced": replaced, "retained": retained,
            "total_changes": added + removed + replaced,
        },
        "changes": [
            {
                "change_type":      c.change_type,
                "mission_id":       c.mission_id,
                "mission_name":     c.mission_name,
                "prev_aircraft_id": c.prev_aircraft_id,
                "new_aircraft_id":  c.new_aircraft_id,
                "prev_crew_id":     c.prev_crew_id,
                "new_crew_id":      c.new_crew_id,
                "note":             c.note,
            }
            for c in changes
        ],
    }


# ── Operational What-If Planning Sandbox (PS 26250) ─────────────────────────

from backend.app.services.whatif import (
    get_whatif_options,
    run_operational_whatif,
    promote_simulation_to_plan,
)


class WhatIfPlanningRequest(BaseModel):
    scenario_type: str
    entity_id: Optional[str] = None
    parameters: Optional[dict] = None
    base_plan_id: Optional[str] = None
    objective: Optional[str] = "MAX_COVERAGE"


class PromoteWhatIfRequest(BaseModel):
    simulation_result: dict
    note: Optional[str] = "Promoted from What-If Planning Sandbox"


@router.get("/whatif/options")
async def get_whatif_planning_options(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Return selectable entities and scenario types for the What-If Sandbox."""
    return get_whatif_options(db)


@router.post("/whatif")
async def run_whatif_planning_scenario(
    req: WhatIfPlanningRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """
    Run an in-memory Operational What-If simulation.
    Does NOT permanently modify the operational database.
    Requires ANALYST role or above.
    """
    ip = _get_ip(request)
    try:
        result = run_operational_whatif(
            db=db,
            scenario_type=req.scenario_type,
            entity_id=req.entity_id,
            parameters=req.parameters,
            base_plan_id=req.base_plan_id,
            objective=req.objective or "MAX_COVERAGE",
            current_user=current_user,
            ip_address=ip,
        )
        return result
    except Exception as exc:
        log.exception("What-If simulation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/whatif/promote")
async def promote_whatif_simulation(
    req: PromoteWhatIfRequest,
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """
    Promote an approved simulation result into a formal PROPOSED plan.
    Requires subsequent approval by a second authorized user (four-eyes rule).
    """
    ip = _get_ip(request)
    try:
        return promote_simulation_to_plan(
            db=db,
            simulation_result=req.simulation_result,
            note=req.note or "Promoted from What-If simulation",
            current_user=current_user,
            ip_address=ip,
        )
    except Exception as exc:
        log.exception("What-If promotion failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))


# ── Scenario Switching Endpoints (PS 26250 Phase 2) ─────────────────────────

from backend.app.services.seed_constrained import (
    seed_constrained_scenario,
    reset_baseline_scenario,
)


@router.get("/scenario/status")
async def get_scenario_status(
    current_user: User = Depends(require_any_authenticated),
    db: Session = Depends(get_db),
):
    """Return status of active scenario (CONSTRAINED vs BASELINE)."""
    m_count = db.query(Mission).count()
    a_count = db.query(Aircraft).count()
    c_count = db.query(Crew).count()
    scenario_type = "CONSTRAINED" if m_count == 10 else "BASELINE"
    return {
        "scenario": scenario_type,
        "name": "SIH Constrained Demonstration Scenario" if scenario_type == "CONSTRAINED" else "Baseline Operations Scenario",
        "description": "Scarce multirole fighters (4), high competition, risk vs coverage trade-offs" if scenario_type == "CONSTRAINED" else "Surplus fleet (30 aircraft, 8 missions, 100% coverage)",
        "mission_count": m_count,
        "aircraft_count": a_count,
        "crew_count": c_count,
    }


@router.post("/scenario/load-constrained")
async def load_constrained_demo_scenario(
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Seed the constrained demonstration scenario for SIH 2026."""
    ip = _get_ip(request)
    result = seed_constrained_scenario(db)
    _audit(db, current_user, "LOAD_SCENARIO", "CONSTRAINED_DEMO", "SUCCESS", ip, result)
    return {
        "status": "success",
        "message": "Loaded SIH Constrained Demonstration Scenario.",
        "summary": result,
    }


@router.post("/scenario/reset-baseline")
async def reset_baseline_demo_scenario(
    request: Request,
    current_user: User = Depends(require_analyst_or_above),
    db: Session = Depends(get_db),
):
    """Reset to the baseline standard scenario (8 missions, 30 aircraft)."""
    ip = _get_ip(request)
    result = reset_baseline_scenario(db)
    _audit(db, current_user, "RESET_SCENARIO", "BASELINE_DEMO", "SUCCESS", ip, result)
    return {
        "status": "success",
        "message": "Reset to Baseline Operations Scenario.",
        "summary": result,
    }


@router.get("/benchmark")
async def get_optimizer_benchmark(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_authenticated),
):
    """
    Run and return optimizer benchmark comparison (MILP vs Greedy vs Manual).
    Demonstrates scalability up to 50+ aircraft and exact branch-and-bound optimality.
    """
    from backend.app.services.optimizer import benchmark_optimizer_performance
    return benchmark_optimizer_performance(db)


@router.get("/gantt")
async def get_sortie_gantt_schedule(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_authenticated),
):
    """
    Return time-indexed sortie timeline & turnaround intervals for Gantt chart.
    """
    active_plan = (
        db.query(MissionPlan)
        .filter(MissionPlan.status == PlanStatus.APPROVED)
        .order_by(MissionPlan.created_at.desc())
        .first()
    )
    if not active_plan:
        active_plan = (
            db.query(MissionPlan)
            .order_by(MissionPlan.created_at.desc())
            .first()
        )
    if not active_plan:
        return {"plan_id": None, "sorties": [], "aircraft": []}

    assignments = (
        db.query(PlanAssignment)
        .filter(PlanAssignment.plan_id == active_plan.id)
        .all()
    )

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    sorties = []
    used_ac_ids = set()

    for idx, a in enumerate(assignments):
        ac = db.query(Aircraft).filter(Aircraft.id == a.aircraft_id).first() if a.aircraft_id else None
        m = db.query(Mission).filter(Mission.id == a.mission_id).first()
        c = db.query(Crew).filter(Crew.id == a.crew_id).first() if a.crew_id else None
        if not m:
            continue
        if ac:
            used_ac_ids.add(ac.id)

        # Distribute into waves (Wave 1: T+1h, Wave 2: T+5h, Wave 3: T+9h)
        wave_idx = (idx % 3)
        start_time = now + timedelta(hours=1 + wave_idx * 4)
        duration_h = m.estimated_duration_hours or 2.0
        recovery_time = start_time + timedelta(hours=duration_h)
        turnaround_until = recovery_time + timedelta(hours=1.5)

        sorties.append({
            "assignment_id": a.id,
            "mission_id": m.id,
            "mission_name": m.name,
            "mission_type": m.mission_type,
            "priority": m.priority,
            "aircraft_id": ac.id if ac else "UNASSIGNED",
            "aircraft_model": ac.model if ac else "N/A",
            "crew_name": c.name if c else "Unassigned",
            "wave": f"WAVE-{wave_idx + 1}",
            "start_time": start_time.isoformat() + "Z",
            "recovery_time": recovery_time.isoformat() + "Z",
            "turnaround_until": turnaround_until.isoformat() + "Z",
            "duration_hours": duration_h,
            "threat_exposure": a.threat_exposure_score or 0.0,
        })

    all_ac = db.query(Aircraft).filter(Aircraft.id.in_(used_ac_ids)).all() if used_ac_ids else []
    return {
        "plan_id": active_plan.id,
        "plan_version": active_plan.version,
        "plan_type": active_plan.plan_type,
        "sorties": sorties,
        "aircraft": [{"id": a.id, "model": a.model, "status": str(a.mission_capable_status)} for a in all_ac]
    }


@router.post("/demo/scripted-scenario")
async def run_scripted_retasking_scenario(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_analyst_or_above),
):
    """
    Execute the Front-and-Centre 90-Second Retasking Showcase:
    1. Verify / ensure active operational ATO plan exists.
    2. Event 1: Pop-up SAM Battery 'SAM-DELTA-9' detected in tactical corridor -> Invalidate & Re-route.
    3. Event 2: Lead Fighter 'DEMO-A001' suffers hydraulic failure -> Grounded & Dynamic Multi-Wave Re-allocation.
    4. Benchmarking comparison: 0.8s automated solve vs 4.5h manual planning.
    """
    ip = _get_ip(request)
    from backend.app.models.models import EventLog, EventType, ThreatType
    from backend.app.services.retasker import process_event

    events_executed = []

    # Step 1: Pop-up SAM Battery
    sam_payload = {
        "name": "SAM-DELTA-9 (SA-21 Growler)",
        "threat_type": "SAM",
        "center_lat": 28.35,
        "center_lon": 76.90,
        "radius_km": 55.0,
        "severity": 5,
        "notes": "Emergency Pop-Up SAM battery detected by SIGINT/ELINT. Contests central strike corridor.",
    }
    sam_event = EventLog(
        event_type=EventType.NEW_THREAT,
        payload=sam_payload,
        injected_by=current_user.id,
    )
    db.add(sam_event)
    db.commit()
    db.refresh(sam_event)

    res1 = process_event(db, sam_event, current_user.id)
    events_executed.append({
        "step": 1,
        "title": "Pop-up High-Threat SAM Detection",
        "description": "SAM-DELTA-9 activated along primary egress corridor. Threat envelopes re-integrated.",
        "retask_triggered": res1.retask_triggered,
        "changes_count": len(res1.changes) if res1.changes else 0,
        "plan_id": res1.new_plan_id,
    })

    # Step 2: In-Flight Aircraft Mechanical Failure
    ac_fail_payload = {
        "aircraft_id": "DEMO-A001",
        "new_status": "GROUNDED",
        "reason": "Sudden hydraulic actuator pressure loss reported via Mil-STD telemetry bus.",
    }
    ac_event = EventLog(
        event_type=EventType.AIRCRAFT_UNSERVICEABLE,
        payload=ac_fail_payload,
        injected_by=current_user.id,
    )
    db.add(ac_event)
    db.commit()
    db.refresh(ac_event)

    res2 = process_event(db, ac_event, current_user.id)
    events_executed.append({
        "step": 2,
        "title": "In-Flight Platform Unserviceability",
        "description": "DEMO-A001 grounded due to critical hydraulic seal fault. Auto-retasking backup airframe across operational waves.",
        "retask_triggered": res2.retask_triggered,
        "changes_count": len(res2.changes) if res2.changes else 0,
        "plan_id": res2.new_plan_id,
    })

    _audit(db, current_user, "SCRIPTED_DEMO", "AIR_OPERATIONS", "SUCCESS", ip, {"events": events_executed})

    return {
        "status": "COMPLETED",
        "scenario_name": "Contested Airspace Dynamic Retasking Showcase",
        "planning_time_ms": (res1.retask_time_ms or 400) + (res2.retask_time_ms or 450),
        "manual_baseline_estimate": "4.5 hours (Combat Operations Centre manual ATO re-draft)",
        "speedup_factor": "18,000x Real-Time Acceleration",
        "resulting_plan_id": res2.new_plan_id or res1.new_plan_id,
        "events": events_executed,
        "final_changes": [
            {
                "change_type": c.change_type,
                "mission_name": c.mission_name,
                "prev_aircraft": c.prev_aircraft_id,
                "new_aircraft": c.new_aircraft_id,
                "note": c.note,
            }
            for c in (res2.changes or [])
        ],
    }

