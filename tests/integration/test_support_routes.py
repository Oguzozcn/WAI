"""Integration tests for the support ticket routes (/api/support).

All writes go to the WAI_DATA_DIR temp dir provided by the conftest client
fixture, so tests never touch the real data/ directory.
"""


def _create(client, **overrides):
    payload = {
        "user_id": "emp_001",
        "display_name": "Alice Employee",
        "role": "individual_contributor",
        "area": "quiz",
        "issue_type": "bug",
        "subject": "Quiz freezes after question 3",
        "description": "The Next button stops responding on the readiness quiz.",
        "additional_comments": "Chrome on macOS.",
    }
    payload.update(overrides)
    return client.post("/api/support/tickets", json=payload)


# ── Create ──────────────────────────────────────────────────────────────────

def test_create_ticket_returns_full_ticket(client):
    resp = _create(client)
    assert resp.status_code == 200
    t = resp.json()
    assert t["ticket_id"] == "TKT-0001"
    assert t["status"] == "new"
    assert t["priority"] == "medium"
    assert t["reporter"]["user_id"] == "emp_001"
    assert t["activity"][0]["event"] == "created"
    assert t["created_at"] and t["updated_at"]


def test_ticket_ids_are_sequential(client):
    assert _create(client).json()["ticket_id"] == "TKT-0001"
    assert _create(client, subject="Second issue").json()["ticket_id"] == "TKT-0002"
    assert _create(client, subject="Third issue").json()["ticket_id"] == "TKT-0003"


def test_create_validates_vocabulary_and_required_fields(client):
    assert _create(client, area="not-an-area").status_code == 400
    assert _create(client, issue_type="not-a-type").status_code == 400
    assert _create(client, subject="   ").status_code == 400
    assert _create(client, description="").status_code == 400
    assert _create(client, user_id=" ").status_code == 400


# ── List: role-scoped visibility ────────────────────────────────────────────

def test_reporter_sees_only_their_own_tickets(client):
    _create(client, user_id="emp_001")
    _create(client, user_id="emp_002", display_name="Bob")

    resp = client.get("/api/support/tickets?user_id=emp_001&role=individual_contributor")
    tickets = resp.json()["tickets"]
    assert len(tickets) == 1
    assert tickets[0]["reporter"]["user_id"] == "emp_001"


def test_developer_sees_the_whole_queue(client):
    _create(client, user_id="emp_001")
    _create(client, user_id="emp_002")
    _create(client, user_id="manager", role="manager")

    resp = client.get("/api/support/tickets?user_id=developer&role=developer")
    assert resp.json()["count"] == 3


def test_get_single_ticket_is_gated_to_reporter_or_developer(client):
    ticket_id = _create(client, user_id="emp_001").json()["ticket_id"]

    assert client.get(f"/api/support/tickets/{ticket_id}?user_id=emp_001&role=individual_contributor").status_code == 200
    assert client.get(f"/api/support/tickets/{ticket_id}?user_id=developer&role=developer").status_code == 200
    assert client.get(f"/api/support/tickets/{ticket_id}?user_id=emp_002&role=individual_contributor").status_code == 403
    assert client.get("/api/support/tickets/TKT-9999?user_id=developer&role=developer").status_code == 404


# ── Triage updates ──────────────────────────────────────────────────────────

def test_update_requires_developer_role(client):
    ticket_id = _create(client).json()["ticket_id"]
    for role in ("", "manager", "individual_contributor"):
        resp = client.patch(f"/api/support/tickets/{ticket_id}", json={"role": role, "status": "in_progress"})
        assert resp.status_code == 403


def test_developer_triage_updates_and_activity_log(client):
    ticket_id = _create(client).json()["ticket_id"]
    resp = client.patch(f"/api/support/tickets/{ticket_id}", json={
        "role": "developer", "display_name": "Dev",
        "status": "in_progress", "priority": "high", "assignee": "developer",
    })
    assert resp.status_code == 200
    t = resp.json()
    assert t["status"] == "in_progress"
    assert t["priority"] == "high"
    assert t["assignee"] == "developer"
    events = [a["event"] for a in t["activity"]]
    assert events == ["created", "status_changed", "priority_changed", "assigned"]


def test_resolution_note_is_stored_and_logged(client):
    ticket_id = _create(client).json()["ticket_id"]
    resp = client.patch(f"/api/support/tickets/{ticket_id}", json={
        "role": "developer", "status": "resolved", "resolution_note": "Fixed the event handler.",
    })
    t = resp.json()
    assert t["status"] == "resolved"
    assert t["resolution_note"] == "Fixed the event handler."
    assert any(a["event"] == "work_note" for a in t["activity"])


def test_invalid_status_and_priority_rejected(client):
    ticket_id = _create(client).json()["ticket_id"]
    assert client.patch(f"/api/support/tickets/{ticket_id}",
                        json={"role": "developer", "status": "nope"}).status_code == 400
    assert client.patch(f"/api/support/tickets/{ticket_id}",
                        json={"role": "developer", "priority": "urgent"}).status_code == 400


def test_closed_ticket_can_only_reopen_to_in_progress(client):
    ticket_id = _create(client).json()["ticket_id"]
    client.patch(f"/api/support/tickets/{ticket_id}", json={"role": "developer", "status": "closed"})

    assert client.patch(f"/api/support/tickets/{ticket_id}",
                        json={"role": "developer", "status": "resolved"}).status_code == 400
    resp = client.patch(f"/api/support/tickets/{ticket_id}",
                        json={"role": "developer", "status": "in_progress"})
    assert resp.status_code == 200
    assert any(a["event"] == "reopened" for a in resp.json()["activity"])


# ── Comments ────────────────────────────────────────────────────────────────

def test_reporter_and_developer_can_comment_others_cannot(client):
    ticket_id = _create(client, user_id="emp_001").json()["ticket_id"]

    ok = client.post(f"/api/support/tickets/{ticket_id}/comments", json={
        "user_id": "emp_001", "display_name": "Alice", "role": "individual_contributor",
        "comment": "It also happens on Firefox.",
    })
    assert ok.status_code == 200
    assert ok.json()["activity"][-1]["event"] == "comment"

    dev = client.post(f"/api/support/tickets/{ticket_id}/comments", json={
        "user_id": "developer", "display_name": "Dev", "role": "developer",
        "comment": "Thanks, reproducing now.",
    })
    assert dev.status_code == 200

    other = client.post(f"/api/support/tickets/{ticket_id}/comments", json={
        "user_id": "emp_002", "display_name": "Bob", "role": "individual_contributor",
        "comment": "Me too!",
    })
    assert other.status_code == 403

    empty = client.post(f"/api/support/tickets/{ticket_id}/comments", json={
        "user_id": "emp_001", "role": "individual_contributor", "comment": "   ",
    })
    assert empty.status_code == 400


# ── Meta + pages ────────────────────────────────────────────────────────────

def test_meta_lists_vocabulary(client):
    meta = client.get("/api/support/meta").json()
    assert "quiz" in meta["areas"]
    assert "bug" in meta["issue_types"]
    assert meta["statuses"] == ["new", "in_progress", "on_hold", "resolved", "closed"]
    assert meta["priorities"] == ["critical", "high", "medium", "low"]


def test_support_pages_are_served(client):
    assert client.get("/support").status_code == 200
    assert client.get("/support-console").status_code == 200
