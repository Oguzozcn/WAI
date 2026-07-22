"""
UAT (User Acceptance Testing) routes
====================================
A developer-only manual acceptance-testing workflow:

- The checklist is PREDEFINED (whole-app coverage, UAT_CHECKLIST below) —
  testers execute it, they don't author it.
- Starting a run snapshots the checklist into a persistent run document
  (data/uat_runs/<dept>/UAT-<n>.json), so history survives checklist edits
  and past runs stay comparable.
- The tester marks each item pass / fail / blocked (with an optional note),
  then requests a report: the run is finalized and an LLM turns the raw
  results into a QA-lead-style summary (verdict, risks, recommendations).
  When the LLM is unavailable the report falls back to a deterministic
  build from the same data — the endpoint never fails on LLM errors.

Role gating follows the app's client-trusted pattern (see dev_console.py):
every endpoint that touches runs requires role == "developer".
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.config import DEFAULT_DEPARTMENT
from src.core.database import DepartmentScopedStore
from src.core.dev_config import get_config
from src.services.llm_client import call_gemini_json

router = APIRouter(prefix="/api/uat", tags=["uat"])

# ── Predefined whole-app checklist (single source of truth) ──────────────────
# Each item: what to do (steps), what success looks like (expected), and the
# page the console's Launch button pops open (launch_url).

ITEM_RESULTS = ["pending", "pass", "fail", "blocked"]
VERDICTS = ["go", "conditional-go", "no-go"]

UAT_CHECKLIST = [
    # Login & access control
    {"id": "AUTH-01", "area": "Login & Access", "title": "Employee login",
     "steps": "Open the login page and sign in with a seeded employee account (e.g. emp_001).",
     "expected": "Redirected to the employee dashboard with course cards.",
     "launch_url": "/login"},
    {"id": "AUTH-02", "area": "Login & Access", "title": "Role gate blocks employees",
     "steps": "While logged in as an employee, open /manager-dashboard directly via the URL bar.",
     "expected": "Bounced back to the dashboard with an 'access denied' toast.",
     "launch_url": "/manager-dashboard"},
    {"id": "AUTH-03", "area": "Login & Access", "title": "Logout",
     "steps": "Use the sidebar account card's Log out button, then try opening any page.",
     "expected": "Returned to the login page; protected pages redirect to /login.",
     "launch_url": "/"},
    # Dashboard
    {"id": "DASH-01", "area": "Dashboard", "title": "Course cards render",
     "steps": "On the dashboard Courses tab, review the lesson cards and the inline expand toggle.",
     "expected": "Cards show correct progress; pagination appears past 5 cards.",
     "launch_url": "/"},
    {"id": "DASH-02", "area": "Dashboard", "title": "Paths tab",
     "steps": "Switch to the Paths tab on the dashboard.",
     "expected": "Enrolled paths are listed with overall progress.",
     "launch_url": "/"},
    # Learning path & lessons
    {"id": "LP-01", "area": "Learning Path & Lessons", "title": "Learning path detail",
     "steps": "Open Learning Path from the sidebar.",
     "expected": "Courses and lessons are listed in order with completion states.",
     "launch_url": "/learning-path"},
    {"id": "LES-01", "area": "Learning Path & Lessons", "title": "Lesson content",
     "steps": "Open a lesson from the dashboard.",
     "expected": "Lesson content renders (headings, lists, key points); Start quiz button is present.",
     "launch_url": "/"},
    # Quiz engine
    {"id": "QUIZ-01", "area": "Quiz Engine", "title": "Take a lesson quiz",
     "steps": "Start a lesson quiz and answer a few questions.",
     "expected": "Inline feedback appears after each answer; progress advances.",
     "launch_url": "/"},
    {"id": "QUIZ-02", "area": "Quiz Engine", "title": "Wrong-answer reflection",
     "steps": "Deliberately answer one question wrong.",
     "expected": "A reflection prompt appears explaining the concept before moving on.",
     "launch_url": "/"},
    {"id": "QUIZ-03", "area": "Quiz Engine", "title": "Finish a quiz",
     "steps": "Complete the quiz to the results screen.",
     "expected": "Score shown with pass/fail and the correct next action (continue, gap review, or remedial course).",
     "launch_url": "/"},
    # Catalog
    {"id": "CAT-01", "area": "Catalog & Enrollment", "title": "Enroll from the catalog",
     "steps": "Open Catalog and enroll in a published path.",
     "expected": "Enrollment is confirmed and the path appears on the dashboard's Paths tab.",
     "launch_url": "/catalog"},
    # Chat coach
    {"id": "CHAT-01", "area": "AI Coach Chat", "title": "Coach chat replies",
     "steps": "Open the chat coach and ask a question about your learning path or progress.",
     "expected": "Typing indicator while waiting; a relevant reply renders in the thread.",
     "launch_url": "/chat"},
    # Manager tools
    {"id": "MGR-01", "area": "Manager Tools", "title": "Team dashboard KPIs",
     "steps": "Log in as the manager and open Team Dashboards.",
     "expected": "KPI cards and the per-report table populate with team data.",
     "launch_url": "/manager-dashboard"},
    {"id": "MGR-02", "area": "Manager Tools", "title": "Excel report export",
     "steps": "Press the export button on the manager dashboard.",
     "expected": "An .xlsx file downloads and opens with formatted team data.",
     "launch_url": "/manager-dashboard"},
    {"id": "KV-01", "area": "Manager Tools", "title": "Knowledge vault upload",
     "steps": "Upload a document in the Knowledge Vault and watch the ingestion job.",
     "expected": "The job completes; conflicts with existing documents are flagged for review.",
     "launch_url": "/knowledge-vault"},
    {"id": "LM-01", "area": "Manager Tools", "title": "Learning materials & versions",
     "steps": "Open Learning Materials; check the document list and a document's version history.",
     "expected": "Documents are listed; version history shows snapshots with restore available.",
     "launch_url": "/learning-materials"},
    {"id": "ELP-01", "area": "Manager Tools", "title": "Edit a learning path",
     "steps": "Open a path in the editor, edit a lesson, check the markdown preview, save, reload.",
     "expected": "The edit persists after reload; preview matches the rendered lesson.",
     "launch_url": "/edit-learning-path"},
    # Team Documentation
    {"id": "TDOC-01", "area": "Team Documentation", "title": "Project creation is manager-only",
     "steps": "As the manager, open Team Documentation and create a new project. Then log in as an employee and confirm no 'New Project' control is offered.",
     "expected": "The manager's project is created and listed; the employee view has no way to create or delete a project but can still open existing ones.",
     "launch_url": "/team-documentation"},
    {"id": "TDOC-02", "area": "Team Documentation", "title": "Link Knowledge Vault sources & add a page",
     "steps": "Open a project, use 'Manage Sources' to check a couple of Knowledge Vault uploads, then add a page via the vault or AI-draft mode.",
     "expected": "Checked sources are saved and pre-checked on reopen; the new page renders with the correct origin badge.",
     "launch_url": "/team-documentation"},
    {"id": "TDOC-03", "area": "Team Documentation", "title": "Documentation Master full synthesis",
     "steps": "With sources linked (TDOC-02), press 'Generate Full Documentation' and wait for it to finish.",
     "expected": "A multi-page doc set is written (overview, glossary, etc. as applicable) grounded in the linked sources, each page badged as synthesized by Documentation Master; re-running replaces only those pages.",
     "launch_url": "/team-documentation"},
    # Developer tools
    {"id": "DEV-01", "area": "Developer Tools", "title": "Agent console",
     "steps": "Log in as the developer and open the Agent Console; edit and save a prompt template.",
     "expected": "The agent graph and config sections load; the template edit saves and persists.",
     "launch_url": "/dev-console"},
    {"id": "DOC-01", "area": "Developer Tools", "title": "Documentation system",
     "steps": "Open Documentation; browse pages; edit-save a page; download TXT and PDF.",
     "expected": "The tree renders, markdown displays, the save persists, both downloads work.",
     "launch_url": "/documentation"},
    # Support
    {"id": "SUP-01", "area": "Support", "title": "Submit a support ticket",
     "steps": "As an employee, submit a ticket from the Support form.",
     "expected": "The ticket appears under 'My tickets' with status New.",
     "launch_url": "/support"},
    {"id": "SUP-02", "area": "Support", "title": "Triage a ticket",
     "steps": "As the developer, open the Support Console; set status/priority and add a work note.",
     "expected": "Changes appear in the ticket's activity timeline and the reporter sees the update.",
     "launch_url": "/support-console"},
    # Global UI
    {"id": "UI-01", "area": "Global UI", "title": "Dark mode",
     "steps": "Toggle dark mode from the sidebar and browse several pages.",
     "expected": "All pages render correctly in dark mode; the choice persists on reload.",
     "launch_url": "/"},
    {"id": "UI-02", "area": "Global UI", "title": "Sidebar collapse & active state",
     "steps": "Collapse the sidebar and navigate between pages.",
     "expected": "The collapsed state persists across pages; the active nav item is highlighted.",
     "launch_url": "/"},
    {"id": "UI-03", "area": "Global UI", "title": "Header avatar & Profile page",
     "steps": "Click the header avatar from a few different pages, then review the Profile page it opens, then use its 'Settings' link to come back.",
     "expected": "The avatar shows your initials and is clickable on every page; Profile shows your real name/role/reports-to and real learning stats (not stuck on placeholders); the Settings link returns you there.",
     "launch_url": "/profile"},
]


class RunCreate(BaseModel):
    user_id: str
    display_name: str = ""
    role: str = ""
    department: str = DEFAULT_DEPARTMENT


class ItemUpdate(BaseModel):
    role: str = ""
    result: str
    note: str = ""


class ReportRequest(BaseModel):
    role: str = ""


def _require_developer(role: str) -> None:
    if role != "developer":
        raise HTTPException(status_code=403, detail="Only a developer can run UAT.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_run_id(store: DepartmentScopedStore) -> str:
    """Sequential, human-readable run numbers (UAT-0001), like ticket ids."""
    highest = 0
    for existing in store.uat_runs_path.glob("UAT-*.json"):
        try:
            highest = max(highest, int(existing.stem.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"UAT-{highest + 1:04d}"


def _compute_summary(run: dict) -> dict:
    counts = {"pass": 0, "fail": 0, "blocked": 0, "pending": 0}
    for item in run["items"]:
        counts[item.get("result", "pending")] = counts.get(item.get("result", "pending"), 0) + 1
    counts["total"] = len(run["items"])
    return counts


def _run_overview(run: dict) -> dict:
    """The list-view projection: everything except the per-item detail."""
    return {
        "run_id": run["run_id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run.get("completed_at", ""),
        "started_by": run.get("started_by", {}),
        "summary": run.get("summary", {}),
        "verdict": (run.get("report") or {}).get("verdict", ""),
    }


# ── AI report (LLM with deterministic fallback, quiz_service pattern) ────────

def _fallback_report(run: dict) -> dict:
    """Deterministic report from the raw counts — used when the LLM is
    unavailable or returns an unusable shape. Same fields as the LLM report."""
    s = run["summary"]
    problems = [i for i in run["items"] if i["result"] in ("fail", "blocked")]
    executed = s["total"] - s["pending"]
    fail_rate = s["fail"] / s["total"] if s["total"] else 0.0

    # "go" requires a clean AND complete run; unexecuted checks weaken coverage.
    if executed == 0:
        verdict = "no-go"
        summary_text = "No checks were actually executed in this run — it proves nothing about release readiness."
    elif s["fail"] == 0 and s["blocked"] == 0 and s["pending"] == 0:
        verdict = "go"
        summary_text = "Every check passed. The application meets the acceptance criteria in this run."
    elif fail_rate >= 0.25:
        verdict = "no-go"
        summary_text = "Too many checks failed for this run to count as acceptance. The failures below need fixes and a re-run."
    else:
        verdict = "conditional-go"
        summary_text = "Most checks passed, but the issues below need review before this run can be treated as a clean acceptance."

    headline = (f"{s['pass']} of {s['total']} checks passed — "
                f"{s['fail']} failed, {s['blocked']} blocked, {s['pending']} not run.")

    key_risks = [
        f"{i['id']} ({i['area']}) — {i['title']}: "
        + (i.get("note") or ("blocked — could not be executed" if i["result"] == "blocked" else "failed"))
        for i in problems
    ] or ["No failed or blocked checks in this run."]

    recommendations = []
    if s["fail"]:
        recommendations.append("Fix the failed checks and re-run the affected checklist areas.")
    if s["blocked"]:
        recommendations.append("Unblock the environment/data issues behind the blocked checks, then re-test them.")
    if s["pending"]:
        recommendations.append(f"{s['pending']} check(s) were never executed — cover them in the next run.")
    if not recommendations:
        recommendations.append("No action needed; archive this run as the current acceptance baseline.")

    return {"verdict": verdict, "headline": headline, "summary": summary_text,
            "key_risks": key_risks, "recommendations": recommendations}


def _generate_report(run: dict) -> dict:
    """QA-lead summary of the run: LLM-written when available, deterministic
    fallback otherwise (mirrors generate_quiz's fallback-on-any-exception)."""
    s = run["summary"]
    run_summary = (
        f"Run {run['run_id']} started {run['started_at']} by "
        f"{run.get('started_by', {}).get('display_name', 'unknown')}. "
        f"Results: {s['pass']} pass, {s['fail']} fail, {s['blocked']} blocked, "
        f"{s['pending']} not run, out of {s['total']} checks."
    )
    results_json = json.dumps(
        [{"id": i["id"], "area": i["area"], "title": i["title"],
          "result": i["result"], "note": i.get("note", "")} for i in run["items"]],
        indent=2,
    )

    report = _fallback_report(run)
    report["source"] = "fallback"
    try:
        tool_config = get_config()["tools"]["generate_uat_report"]
        prompt = tool_config["prompt_template"].format(
            run_summary=run_summary, results_json=results_json,
        )
        llm_data = call_gemini_json(prompt, model=tool_config.get("model"))
        if llm_data.get("verdict") not in VERDICTS:
            raise ValueError(f"LLM verdict must be one of {VERDICTS}.")
        if not str(llm_data.get("headline", "")).strip() or not str(llm_data.get("summary", "")).strip():
            raise ValueError("LLM response missing headline/summary.")
        risks = llm_data.get("key_risks")
        recs = llm_data.get("recommendations")
        if not isinstance(risks, list) or not isinstance(recs, list):
            raise ValueError("LLM key_risks/recommendations must be lists.")
        report = {
            "verdict": llm_data["verdict"],
            "headline": str(llm_data["headline"]).strip(),
            "summary": str(llm_data["summary"]).strip(),
            "key_risks": [str(r) for r in risks],
            "recommendations": [str(r) for r in recs],
            "source": "llm",
        }
    except Exception as e:
        print(f"[generate_uat_report] LLM call failed ({e}), using fallback report.")

    report["generated_at"] = _now()
    return report


# ── Checklist (predefined vocabulary, like support's /meta) ──────────────────

@router.get("/checklist")
async def api_uat_checklist():
    areas = []
    for item in UAT_CHECKLIST:
        if item["area"] not in areas:
            areas.append(item["area"])
    return {"areas": areas, "items": UAT_CHECKLIST, "results": ITEM_RESULTS,
            "verdicts": VERDICTS}


# ── Runs ─────────────────────────────────────────────────────────────────────

@router.post("/runs")
async def api_create_run(body: RunCreate):
    _require_developer(body.role)
    if not body.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required.")

    store = DepartmentScopedStore(body.department)
    run_id = _next_run_id(store)
    run = {
        "run_id": run_id,
        "department": body.department,
        "status": "in_progress",
        "started_at": _now(),
        "completed_at": "",
        "started_by": {
            "user_id": body.user_id,
            "display_name": body.display_name or body.user_id,
        },
        # Snapshot the checklist into the run so history stays stable even if
        # UAT_CHECKLIST changes between runs.
        "items": [dict(item, result="pending", note="", marked_at="")
                  for item in UAT_CHECKLIST],
        "report": None,
    }
    run["summary"] = _compute_summary(run)
    store.write_uat_run(run_id, run)
    return run


@router.get("/runs")
async def api_list_runs(role: str = "", department: str = DEFAULT_DEPARTMENT):
    _require_developer(role)
    store = DepartmentScopedStore(department)
    runs = [_run_overview(r) for r in store.list_uat_runs()]
    return {"runs": runs, "count": len(runs)}


@router.get("/runs/{run_id}")
async def api_get_run(run_id: str, role: str = "", department: str = DEFAULT_DEPARTMENT):
    _require_developer(role)
    store = DepartmentScopedStore(department)
    run = store.read_uat_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"UAT run '{run_id}' not found.")
    return run


@router.patch("/runs/{run_id}/items/{item_id}")
async def api_update_item(run_id: str, item_id: str, body: ItemUpdate,
                          department: str = DEFAULT_DEPARTMENT):
    _require_developer(body.role)
    if body.result not in ITEM_RESULTS:
        raise HTTPException(status_code=400,
                            detail=f"result must be one of: {', '.join(ITEM_RESULTS)}")
    store = DepartmentScopedStore(department)
    run = store.read_uat_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"UAT run '{run_id}' not found.")
    if run["status"] == "completed":
        raise HTTPException(status_code=400,
                            detail="This run is completed — start a new run to test again.")

    item = next((i for i in run["items"] if i["id"] == item_id), None)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"Checklist item '{item_id}' not found in this run.")

    item["result"] = body.result
    item["note"] = body.note.strip()
    item["marked_at"] = _now() if body.result != "pending" else ""
    run["summary"] = _compute_summary(run)
    store.write_uat_run(run_id, run)
    return {"item": item, "summary": run["summary"]}


@router.post("/runs/{run_id}/report")
async def api_generate_report(run_id: str, body: ReportRequest,
                              department: str = DEFAULT_DEPARTMENT):
    """Finalize the run and generate (or regenerate) the AI report."""
    _require_developer(body.role)
    store = DepartmentScopedStore(department)
    run = store.read_uat_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"UAT run '{run_id}' not found.")

    run["summary"] = _compute_summary(run)
    if run["status"] != "completed":
        run["status"] = "completed"
        run["completed_at"] = _now()
    run["report"] = _generate_report(run)
    store.write_uat_run(run_id, run)
    return run
