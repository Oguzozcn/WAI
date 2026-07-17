"""
TEAP Reporting Tools
=====================
ADK function tools split across two tiers:

Tier 1 (PUSH) — Used by Department Reporter:
  - synthesize_department_kpi(): Reads user progress, strips PII, writes KPI payload

Tier 3 (AGGREGATE) — Used by Corporate Report Agent:
  - read_kpi_payloads(): Read-only access to KPI store
  - generate_executive_email(): Formats cross-department email report
"""

import json
from datetime import datetime, date

from src.core.database import DepartmentScopedStore, KPIStoreReader
from src.core.models import (
    KPIPayload, WorkforceMetrics, LearningMetrics,
    AssessmentMetrics, KnowledgeBaseMetrics, RiskIndicators,
)
from src.core.config import (
    DEFAULT_DEPARTMENT, SCHEMA_VERSION, AT_RISK_READINESS_THRESHOLD,
    AT_RISK_PERCENTAGE_THRESHOLD, PASS_THRESHOLD,
)


# ══════════════════════════════════════════════════════════
# TIER 1: PUSH — Department Reporter Tools
# ══════════════════════════════════════════════════════════

def synthesize_department_kpi(
    department: str = DEFAULT_DEPARTMENT,
    report_date: str = "",
) -> dict:
    """Synthesize an anonymized KPI payload from department user progress data.

    This is the ONE-WAY PUSH across the department boundary.
    Reads all user progress files, aggregates metrics, strips all PII,
    validates against schema v1.0, and writes to the central KPI store.

    CRITICAL: No employee IDs, names, or raw answers are included.
    Only aggregate counts and percentages cross the boundary.

    Args:
        department: The department to synthesize KPIs for
        report_date: ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        Confirmation of KPI payload generation with summary metrics.
    """
    if not report_date:
        report_date = date.today().isoformat()

    store = DepartmentScopedStore(department)
    all_progress = store.read_all_user_progress()

    # ── Calculate Workforce Metrics ──
    total_enrolled = len(all_progress)
    active_learners = sum(
        1 for p in all_progress
        if p.get("current_state") not in ("enrolled", "completed", None)
    )
    inactive_count = total_enrolled - active_learners

    # ── Calculate Learning Metrics ──
    all_completed_courses = []
    for p in all_progress:
        all_completed_courses.extend(p.get("completed_courses", []))

    courses_completed = len(all_completed_courses)
    total_possible = total_enrolled * 10  # MAX_COURSES per user
    avg_completion = (courses_completed / total_possible * 100) if total_possible > 0 else 0.0

    # Count learning paths generated (users with a learning_path_id)
    paths_generated = sum(1 for p in all_progress if p.get("learning_path_id"))

    # ── Calculate Assessment Metrics ──
    total_quizzes = 0
    total_quiz_score = 0.0
    assessments_passed = 0
    assessments_failed = 0
    bypass_attempts = 0
    bypass_lockouts = 0

    for p in all_progress:
        attempts = p.get("quiz_attempts", [])
        total_quizzes += len(attempts)
        for attempt in attempts:
            total_quiz_score += attempt.get("score", 0.0)

        if p.get("current_state") in ("passed", "completed"):
            assessments_passed += 1
        elif p.get("current_state") == "failed":
            assessments_failed += 1

        bypass_attempts += p.get("bypass_attempts", 0)
        if p.get("bypass_locked"):
            bypass_lockouts += 1

    avg_quiz_score = (total_quiz_score / total_quizzes * 100) if total_quizzes > 0 else 0.0
    total_assessments = assessments_passed + assessments_failed
    pass_rate = (assessments_passed / total_assessments * 100) if total_assessments > 0 else 0.0

    # Count luck eliminations
    luck_eliminations = sum(
        1 for p in all_progress
        if any(v >= 2 for v in p.get("error_retention_matrix", {}).values())
    )

    # ── Calculate KB Metrics ──
    existing_docs = store.read_knowledge_base()
    conflicts = store.read_conflicts()
    pending_conflicts = [c for c in conflicts if c.get("status") == "pending"]
    resolved_conflicts = [c for c in conflicts if c.get("status") == "resolved"]

    # ── Calculate Risk Indicators ──
    scores = [p.get("readiness_score", 0.0) for p in all_progress]
    avg_readiness = sum(scores) / len(scores) if scores else 0.0
    at_risk_count = sum(1 for s in scores if s < AT_RISK_READINESS_THRESHOLD)
    below_threshold_pct = (at_risk_count / total_enrolled * 100) if total_enrolled > 0 else 0.0

    # ── Identify Top Gap Areas (no PII — topic names only) ──
    gap_counter: dict[str, int] = {}
    for p in all_progress:
        for concept, count in p.get("error_retention_matrix", {}).items():
            gap_counter[concept] = gap_counter.get(concept, 0) + count

    top_gaps = sorted(gap_counter, key=gap_counter.get, reverse=True)[:10]

    # ── Build KPI Payload ──
    payload = KPIPayload(
        schema_version=SCHEMA_VERSION,
        department_id=department,
        report_date=report_date,
        reporting_period="daily",
        workforce_metrics=WorkforceMetrics(
            total_enrolled=total_enrolled,
            active_learners=active_learners,
            inactive_count=inactive_count,
        ),
        learning_metrics=LearningMetrics(
            courses_completed_period=courses_completed,
            avg_completion_rate_pct=round(avg_completion, 1),
            learning_paths_generated=paths_generated,
            avg_time_per_course_hours=1.5,  # Estimated from agenda structure
        ),
        assessment_metrics=AssessmentMetrics(
            quizzes_administered=total_quizzes,
            avg_quiz_score_pct=round(avg_quiz_score, 1),
            assessments_passed=assessments_passed,
            assessments_failed=assessments_failed,
            pass_rate_pct=round(pass_rate, 1),
            bypass_attempts=bypass_attempts,
            bypass_lockouts=bypass_lockouts,
            luck_eliminations_triggered=luck_eliminations,
        ),
        knowledge_base_metrics=KnowledgeBaseMetrics(
            documents_ingested=len(existing_docs),
            conflicts_detected=len(conflicts),
            conflicts_resolved=len(resolved_conflicts),
            conflicts_pending_review=len(pending_conflicts),
        ),
        risk_indicators=RiskIndicators(
            at_risk_employee_count=at_risk_count,
            avg_readiness_score=round(avg_readiness, 2),
            employees_below_threshold_pct=round(below_threshold_pct, 1),
        ),
        top_gap_areas=top_gaps,
    )

    # Serialize and validate
    payload_dict = payload.to_dict()

    # Write to central KPI store (one-way push)
    file_path = store.write_kpi_payload(report_date, payload_dict)

    return {
        "status": "success",
        "department": department,
        "report_date": report_date,
        "file_path": file_path,
        "summary": {
            "total_enrolled": total_enrolled,
            "active_learners": active_learners,
            "avg_readiness_score": round(avg_readiness, 2),
            "at_risk_count": at_risk_count,
            "pass_rate_pct": round(pass_rate, 1),
        },
        "message": (
            f"KPI payload for '{department}' on {report_date} has been "
            f"validated against schema v{SCHEMA_VERSION} and written to the "
            f"central store. No PII was included."
        ),
    }


# ══════════════════════════════════════════════════════════
# TIER 3: AGGREGATE — Corporate Report Agent Tools
# ══════════════════════════════════════════════════════════

def read_kpi_payloads(
    report_date: str = "",
    departments: list[str] | None = None,
) -> dict:
    """Read KPI payloads from the central store for a given date.

    This is a READ-ONLY operation. The tool cannot write, modify,
    or delete any files. It reads exclusively from data/kpi_store/.

    Args:
        report_date: ISO date string (YYYY-MM-DD). Defaults to today.
        departments: Optional list of department IDs to filter.
                     If empty/None, reads all available departments.

    Returns:
        List of validated KPI payloads and available metadata.
    """
    if not report_date:
        report_date = date.today().isoformat()

    reader = KPIStoreReader()
    payloads = reader.read_payloads(report_date, departments)

    if not payloads:
        available_dates = reader.list_available_dates()
        return {
            "status": "no_data",
            "report_date": report_date,
            "message": (
                f"No KPI payloads found for date '{report_date}'."
                + (f" Available dates: {available_dates}" if available_dates else "")
            ),
        }

    return {
        "status": "success",
        "report_date": report_date,
        "department_count": len(payloads),
        "departments": [p["department_id"] for p in payloads],
        "payloads": payloads,
    }


def generate_executive_email(
    report_date: str = "",
    period: str = "daily",
) -> dict:
    """Generate a professional executive email summarizing KPI data.

    Reads all available KPI payloads for the given date and compiles
    them into an email-ready format for transition leadership.

    This tool reads ONLY from the KPI store. It has NO access to
    user progress files, agent sessions, or departmental data.

    Args:
        report_date: ISO date string (YYYY-MM-DD). Defaults to today.
        period: Reporting period label - "daily", "weekly", or "monthly"

    Returns:
        Formatted email structure with subject, body, and highlights.
    """
    if not report_date:
        report_date = date.today().isoformat()

    reader = KPIStoreReader()
    payloads = reader.read_payloads(report_date)

    if not payloads:
        return {
            "status": "no_data",
            "message": f"No KPI data available for {report_date}. Cannot generate email.",
        }

    # Aggregate cross-department metrics
    total_enrolled = 0
    total_active = 0
    total_at_risk = 0
    all_readiness_scores = []
    all_gap_areas = []
    high_priority_depts = []

    dept_summaries = []
    for payload in payloads:
        dept = payload["department_id"]
        wf = payload["workforce_metrics"]
        risk = payload["risk_indicators"]
        assess = payload["assessment_metrics"]

        total_enrolled += wf["total_enrolled"]
        total_active += wf["active_learners"]
        total_at_risk += risk["at_risk_employee_count"]
        all_readiness_scores.append(risk["avg_readiness_score"])
        all_gap_areas.extend(payload.get("top_gap_areas", []))

        # Check for high priority
        if (risk["avg_readiness_score"] < AT_RISK_READINESS_THRESHOLD or
                risk["employees_below_threshold_pct"] > AT_RISK_PERCENTAGE_THRESHOLD):
            high_priority_depts.append(dept)

        dept_summaries.append({
            "department": dept,
            "enrolled": wf["total_enrolled"],
            "active": wf["active_learners"],
            "readiness": f"{risk['avg_readiness_score']:.0%}",
            "at_risk": risk["at_risk_employee_count"],
            "pass_rate": f"{assess['pass_rate_pct']:.1f}%",
            "is_high_priority": dept in high_priority_depts,
        })

    overall_readiness = (
        sum(all_readiness_scores) / len(all_readiness_scores)
        if all_readiness_scores else 0.0
    )

    # Build email
    email = {
        "subject": f"TEAP {period.capitalize()} Report — {report_date}",
        "to": "Transition Leadership Team",
        "generated_at": datetime.utcnow().isoformat(),
        "high_priority_alerts": high_priority_depts,
        "executive_summary": {
            "total_departments_reporting": len(payloads),
            "total_enrolled": total_enrolled,
            "total_active_learners": total_active,
            "overall_readiness_score": f"{overall_readiness:.0%}",
            "total_at_risk": total_at_risk,
            "high_priority_departments": high_priority_depts,
        },
        "department_breakdown": dept_summaries,
        "top_gap_areas_cross_department": list(dict.fromkeys(all_gap_areas))[:10],
        "recommendations": _generate_recommendations(
            overall_readiness, total_at_risk, total_enrolled, high_priority_depts
        ),
    }

    return email


def _generate_recommendations(
    readiness: float,
    at_risk: int,
    total: int,
    high_priority: list[str],
) -> list[str]:
    """Generate actionable recommendations based on metrics."""
    recs = []

    if high_priority:
        recs.append(
            f"⚠️ HIGH PRIORITY: Department(s) {', '.join(high_priority)} "
            f"require immediate intervention — readiness is below {AT_RISK_READINESS_THRESHOLD:.0%}."
        )

    if at_risk > 0 and total > 0:
        pct = (at_risk / total) * 100
        if pct > AT_RISK_PERCENTAGE_THRESHOLD:
            recs.append(
                f"🔴 {at_risk} employees ({pct:.0f}%) are at risk of not meeting "
                f"readiness targets. Consider scheduling additional support sessions."
            )
        else:
            recs.append(
                f"🟡 {at_risk} employees are flagged at-risk. Current levels are "
                f"within acceptable range but should be monitored."
            )

    if readiness >= 0.80:
        recs.append(
            "✅ Overall readiness is on track. Continue current learning cadence."
        )
    elif readiness >= 0.60:
        recs.append(
            "📊 Readiness is progressing but below target. Review gap areas "
            "and consider targeted coaching interventions."
        )
    else:
        recs.append(
            "🚨 Readiness is significantly below target. Immediate review of "
            "learning paths and resource allocation is recommended."
        )

    return recs
