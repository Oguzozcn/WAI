"""
Support Ticket routes
=====================
An ITSM-style ticketing flow (ServiceNow-inspired) scoped to the MVP:

- Employees/managers submit tickets from the /support form and can follow
  the status of their own tickets.
- The developer works the queue from /support-console: triage (priority,
  assignment), status lifecycle, work notes, and resolution.

Lifecycle:  new -> in_progress -> on_hold -> resolved -> closed
(any forward/backward move between open states is allowed; closed is final
except an explicit reopen back to in_progress).

Every mutation is appended to the ticket's activity log, so the detail view
can render a ServiceNow-style timeline.

Role gating follows the app's client-trusted pattern (see dev_console.py):
the client sends role/user_id along with the request; reads are filtered so
non-developers only ever see their own tickets.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.core.config import DEFAULT_DEPARTMENT
from src.core.database import DepartmentScopedStore

router = APIRouter(prefix="/api/support", tags=["support"])

# ── Vocabulary (single source of truth; the frontend mirrors these) ─────────

TICKET_AREAS = [
    "dashboard", "learning-path", "lesson", "quiz", "chat-coach",
    "catalog", "knowledge-vault", "team-dashboards", "login-auth", "other",
]
ISSUE_TYPES = [
    "bug", "ui-visual", "performance", "data-incorrect",
    "feature-request", "question", "other",
]
STATUSES = ["new", "in_progress", "on_hold", "resolved", "closed"]
PRIORITIES = ["critical", "high", "medium", "low"]


class TicketCreate(BaseModel):
    user_id: str
    display_name: str = ""
    role: str = ""
    department: str = DEFAULT_DEPARTMENT
    area: str
    issue_type: str
    subject: str
    description: str
    additional_comments: str = ""


class TicketUpdate(BaseModel):
    role: str = ""
    display_name: str = ""
    status: str | None = None
    priority: str | None = None
    assignee: str | None = None
    resolution_note: str | None = None


class TicketComment(BaseModel):
    user_id: str
    display_name: str = ""
    role: str = ""
    comment: str


def _require_developer(role: str) -> None:
    if role != "developer":
        raise HTTPException(status_code=403, detail="Only a developer can manage tickets.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_ticket_id(store: DepartmentScopedStore) -> str:
    """Sequential, human-readable ticket numbers (TKT-0001), ServiceNow-style."""
    highest = 0
    for existing in store.tickets_path.glob("TKT-*.json"):
        try:
            highest = max(highest, int(existing.stem.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return f"TKT-{highest + 1:04d}"


def _activity(by_id: str, by_name: str, event: str, detail: str = "") -> dict:
    return {"at": _now(), "by_user_id": by_id, "by": by_name or by_id, "event": event, "detail": detail}


# ── Create ───────────────────────────────────────────────────────────────────

@router.post("/tickets")
async def api_create_ticket(body: TicketCreate):
    if not body.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required.")
    if body.area not in TICKET_AREAS:
        raise HTTPException(status_code=400, detail=f"area must be one of: {', '.join(TICKET_AREAS)}")
    if body.issue_type not in ISSUE_TYPES:
        raise HTTPException(status_code=400, detail=f"issue_type must be one of: {', '.join(ISSUE_TYPES)}")
    if not body.subject.strip():
        raise HTTPException(status_code=400, detail="A short subject line is required.")
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Please describe the issue.")

    store = DepartmentScopedStore(body.department)
    ticket_id = _next_ticket_id(store)
    ticket = {
        "ticket_id": ticket_id,
        "department": body.department,
        "subject": body.subject.strip(),
        "area": body.area,
        "issue_type": body.issue_type,
        "description": body.description.strip(),
        "additional_comments": body.additional_comments.strip(),
        "status": "new",
        "priority": "medium",
        "assignee": "",
        "resolution_note": "",
        "reporter": {
            "user_id": body.user_id,
            "display_name": body.display_name or body.user_id,
            "role": body.role,
        },
        "created_at": _now(),
        "activity": [_activity(body.user_id, body.display_name, "created", "Ticket submitted")],
    }
    store.write_ticket(ticket_id, ticket)
    return ticket


# ── Read ─────────────────────────────────────────────────────────────────────

@router.get("/tickets")
async def api_list_tickets(user_id: str = "", role: str = "", department: str = DEFAULT_DEPARTMENT):
    """Developer sees the full department queue; everyone else only their own."""
    store = DepartmentScopedStore(department)
    tickets = store.list_tickets()
    if role != "developer":
        tickets = [t for t in tickets if t.get("reporter", {}).get("user_id") == user_id]
    return {"tickets": tickets, "count": len(tickets)}


@router.get("/tickets/{ticket_id}")
async def api_get_ticket(ticket_id: str, user_id: str = "", role: str = "",
                         department: str = DEFAULT_DEPARTMENT):
    store = DepartmentScopedStore(department)
    ticket = store.read_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found.")
    if role != "developer" and ticket.get("reporter", {}).get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="You can only view your own tickets.")
    return ticket


# ── Triage / update (developer only) ─────────────────────────────────────────

@router.patch("/tickets/{ticket_id}")
async def api_update_ticket(ticket_id: str, body: TicketUpdate,
                            department: str = DEFAULT_DEPARTMENT):
    _require_developer(body.role)
    store = DepartmentScopedStore(department)
    ticket = store.read_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found.")

    actor = body.display_name or "Developer"
    changed = False

    if body.status is not None and body.status != ticket["status"]:
        if body.status not in STATUSES:
            raise HTTPException(status_code=400, detail=f"status must be one of: {', '.join(STATUSES)}")
        if ticket["status"] == "closed" and body.status != "in_progress":
            raise HTTPException(status_code=400, detail="A closed ticket can only be reopened to in_progress.")
        event = "reopened" if ticket["status"] == "closed" else "status_changed"
        ticket["activity"].append(_activity("developer", actor, event,
                                            f"{ticket['status']} -> {body.status}"))
        ticket["status"] = body.status
        changed = True

    if body.priority is not None and body.priority != ticket["priority"]:
        if body.priority not in PRIORITIES:
            raise HTTPException(status_code=400, detail=f"priority must be one of: {', '.join(PRIORITIES)}")
        ticket["activity"].append(_activity("developer", actor, "priority_changed",
                                            f"{ticket['priority']} -> {body.priority}"))
        ticket["priority"] = body.priority
        changed = True

    if body.assignee is not None and body.assignee != ticket.get("assignee", ""):
        ticket["activity"].append(_activity("developer", actor, "assigned",
                                            body.assignee or "unassigned"))
        ticket["assignee"] = body.assignee
        changed = True

    if body.resolution_note is not None and body.resolution_note.strip():
        ticket["resolution_note"] = body.resolution_note.strip()
        ticket["activity"].append(_activity("developer", actor, "work_note",
                                            body.resolution_note.strip()))
        changed = True

    if changed:
        store.write_ticket(ticket_id, ticket)
    return ticket


# ── Comments (reporter or developer) ─────────────────────────────────────────

@router.post("/tickets/{ticket_id}/comments")
async def api_comment_ticket(ticket_id: str, body: TicketComment,
                             department: str = DEFAULT_DEPARTMENT):
    if not body.comment.strip():
        raise HTTPException(status_code=400, detail="Comment cannot be empty.")
    store = DepartmentScopedStore(department)
    ticket = store.read_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket '{ticket_id}' not found.")
    is_reporter = ticket.get("reporter", {}).get("user_id") == body.user_id
    if body.role != "developer" and not is_reporter:
        raise HTTPException(status_code=403, detail="You can only comment on your own tickets.")
    ticket["activity"].append(_activity(body.user_id, body.display_name, "comment",
                                        body.comment.strip()))
    store.write_ticket(ticket_id, ticket)
    return ticket


# ── Vocabulary for the frontend dropdowns ────────────────────────────────────

@router.get("/meta")
async def api_support_meta():
    return {
        "areas": TICKET_AREAS,
        "issue_types": ISSUE_TYPES,
        "statuses": STATUSES,
        "priorities": PRIORITIES,
    }
