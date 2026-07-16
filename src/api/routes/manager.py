"""Manager Dashboard API Routes.

Provides three KPI bucket endpoints for the manager view:
  - /team-kpis     → Team/Managerial Bucket (aggregated health)
  - /reports       → Individual Bucket (direct reports progress)
  - /strategic     → Strategic Bucket (team vs department baseline)
"""

from fastapi import APIRouter, HTTPException
from WAI_agent.shared.persistence import DepartmentScopedStore, KPIStoreReader
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT, AT_RISK_READINESS_THRESHOLD, PASS_THRESHOLD

router = APIRouter(prefix="/api/manager", tags=["manager"])


def _get_direct_reports(store: DepartmentScopedStore, manager_id: str) -> list[dict]:
    """Return all user progress records where manager_id matches."""
    all_progress = store.read_all_user_progress()
    return [p for p in all_progress if p.get("manager_id") == manager_id]


def _status_label(progress: dict) -> str:
    """Return a human-readable status label for a user's progress."""
    state = progress.get("current_state", "enrolled")
    mapping = {
        "completed": "Completed",
        "passed": "Completed",
        "PENDING_VERIFIED_HUMAN_APPROVAL": "Awaiting Sign-off",
        "enrolled": "Not Started",
        "bypass_locked": "Bypass Locked",
        "failed": "Needs Support",
    }
    if state in mapping:
        return mapping[state]
    # "progressing" states
    return "In Progress"


def _rag_color(readiness_score: float) -> str:
    """Return Red/Amber/Green color based on readiness score."""
    if readiness_score >= PASS_THRESHOLD:
        return "green"
    elif readiness_score >= AT_RISK_READINESS_THRESHOLD:
        return "amber"
    return "red"


# ── Bucket 1: Team / Managerial KPIs ─────────────────────────────────────────

@router.get("/{manager_id}/team-kpis")
async def manager_team_kpis(manager_id: str, department: str = DEFAULT_DEPARTMENT):
    """Team Bucket — aggregated health metrics for all direct reports.

    Returns:
        - team_size, active_learners, completion_rate, avg_readiness_score
        - pass_rate, at_risk_count, top_gap_areas
    """
    store = DepartmentScopedStore(department)
    reports = _get_direct_reports(store, manager_id)

    if not reports:
        raise HTTPException(
            status_code=404,
            detail=f"No direct reports found for manager '{manager_id}' in department '{department}'.",
        )

    total = len(reports)
    active = sum(
        1 for p in reports
        if p.get("current_state") not in ("enrolled", "completed", "passed", None)
    )
    completed = sum(1 for p in reports if p.get("current_state") in ("completed", "passed"))

    # Completion rate: avg of (completed_courses / 10) per employee
    completion_rates = [
        len(p.get("completed_courses", [])) / 10 for p in reports
    ]
    avg_completion_rate = sum(completion_rates) / total if total else 0.0

    # Readiness
    readiness_scores = [p.get("readiness_score", 0.0) for p in reports]
    avg_readiness = sum(readiness_scores) / total if total else 0.0
    at_risk_count = sum(1 for s in readiness_scores if s < AT_RISK_READINESS_THRESHOLD)

    # Pass rate
    assessed = sum(
        1 for p in reports
        if p.get("current_state") in ("completed", "passed", "failed")
    )
    pass_rate = (completed / assessed * 100) if assessed > 0 else 0.0

    # Top gap areas (de-duplicated concept tags across the team)
    gap_counter: dict[str, int] = {}
    for p in reports:
        for concept, count in p.get("error_retention_matrix", {}).items():
            gap_counter[concept] = gap_counter.get(concept, 0) + count
    top_gaps = sorted(gap_counter, key=gap_counter.get, reverse=True)[:5]  # type: ignore[arg-type]

    return {
        "manager_id": manager_id,
        "department": department,
        "team_size": total,
        "active_learners": active,
        "completed_count": completed,
        "avg_completion_rate_pct": round(avg_completion_rate * 100, 1),
        "avg_readiness_score": round(avg_readiness, 2),
        "at_risk_count": at_risk_count,
        "pass_rate_pct": round(pass_rate, 1),
        "top_gap_areas": top_gaps,
        "rag_status": _rag_color(avg_readiness),
    }


# ── Bucket 2: Individual Progress (Direct Reports) ────────────────────────────

@router.get("/{manager_id}/reports")
async def manager_direct_reports(manager_id: str, department: str = DEFAULT_DEPARTMENT):
    """Individual Bucket — one row per direct report showing their learning progress.

    Returns per-employee:
        - display_name, status label, current_course_id,
          completion_rate, readiness_score, rag_color
    """
    store = DepartmentScopedStore(department)
    reports = _get_direct_reports(store, manager_id)

    if not reports:
        raise HTTPException(
            status_code=404,
            detail=f"No direct reports found for manager '{manager_id}' in department '{department}'.",
        )

    rows = []
    for p in reports:
        completed_courses = p.get("completed_courses", [])
        completion_rate = round(len(completed_courses) / 10 * 100, 1)
        readiness = p.get("readiness_score", 0.0)
        rows.append({
            "user_id": p.get("user_id", ""),
            "display_name": p.get("display_name", p.get("user_id", "")),
            "status": _status_label(p),
            "current_course_id": p.get("current_course_id", ""),
            "courses_completed": len(completed_courses),
            "completion_rate_pct": completion_rate,
            "readiness_score": round(readiness, 2),
            "rag_color": _rag_color(readiness),
            "is_at_risk": readiness < AT_RISK_READINESS_THRESHOLD,
        })

    # Sort by readiness ascending — at-risk employees appear at the top
    rows.sort(key=lambda r: r["readiness_score"])

    return {
        "manager_id": manager_id,
        "department": department,
        "report_count": len(rows),
        "reports": rows,
    }


# ── Bucket 3: Strategic (Team vs Department Baseline) ────────────────────────

@router.get("/{manager_id}/strategic")
async def manager_strategic(manager_id: str, department: str = DEFAULT_DEPARTMENT):
    """Strategic Bucket — compares the manager's team metrics against the department KPI baseline.

    Reads from the central KPI store so this data is PII-free and pre-aggregated.
    Falls back to department-level live calculation if no KPI payload exists yet.
    """
    store = DepartmentScopedStore(department)
    reports = _get_direct_reports(store, manager_id)

    if not reports:
        raise HTTPException(
            status_code=404,
            detail=f"No direct reports found for manager '{manager_id}' in department '{department}'.",
        )

    # Team metrics (live)
    total = len(reports)
    team_readiness_scores = [p.get("readiness_score", 0.0) for p in reports]
    team_avg_readiness = sum(team_readiness_scores) / total if total else 0.0
    team_completion = sum(
        len(p.get("completed_courses", [])) / 10 for p in reports
    ) / total * 100 if total else 0.0

    # Department baseline from KPI store (most recent payload)
    reader = KPIStoreReader()
    available_dates = reader.list_available_dates()
    dept_avg_readiness = None
    dept_avg_completion = None

    if available_dates:
        latest_date = sorted(available_dates)[-1]
        payloads = reader.read_payloads(latest_date, [department])
        if payloads:
            payload = payloads[0]
            dept_avg_readiness = payload.get("risk_indicators", {}).get("avg_readiness_score")
            dept_avg_completion = payload.get("learning_metrics", {}).get("avg_completion_rate_pct")

    # If no KPI payload exists yet, fall back to all-department live calculation
    if dept_avg_readiness is None:
        all_progress = store.read_all_user_progress()
        all_scores = [p.get("readiness_score", 0.0) for p in all_progress]
        dept_avg_readiness = sum(all_scores) / len(all_scores) if all_scores else 0.0
        dept_avg_completion = (
            sum(len(p.get("completed_courses", [])) / 10 for p in all_progress)
            / len(all_progress) * 100
            if all_progress else 0.0
        )

    readiness_delta = round(team_avg_readiness - dept_avg_readiness, 2)
    completion_delta = round(team_completion - (dept_avg_completion or 0.0), 1)

    return {
        "manager_id": manager_id,
        "department": department,
        "team": {
            "avg_readiness_score": round(team_avg_readiness, 2),
            "avg_completion_rate_pct": round(team_completion, 1),
        },
        "department_baseline": {
            "avg_readiness_score": round(dept_avg_readiness, 2),
            "avg_completion_rate_pct": round(dept_avg_completion or 0.0, 1),
        },
        "delta": {
            "readiness": readiness_delta,
            "readiness_label": "above" if readiness_delta >= 0 else "below",
            "completion_pct": completion_delta,
            "completion_label": "above" if completion_delta >= 0 else "below",
        },
    }
