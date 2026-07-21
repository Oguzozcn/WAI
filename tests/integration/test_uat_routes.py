"""Integration tests for the UAT console routes (/api/uat).

All writes go to the WAI_DATA_DIR temp dir provided by the conftest client
fixture, so tests never touch the real data/ directory. The AI report's LLM
call is exercised through the mock_gemini fixture (valid JSON for the LLM
path, an Exception for the deterministic fallback path).
"""

import json


def _new_run(client, role="developer"):
    return client.post("/api/uat/runs", json={
        "user_id": "developer", "display_name": "Dev", "role": role,
    })


def _mark(client, run_id, item_id, result, note="", role="developer"):
    return client.patch(f"/api/uat/runs/{run_id}/items/{item_id}",
                        json={"role": role, "result": result, "note": note})


# ── Checklist (predefined vocabulary) ───────────────────────────────────────

def test_checklist_is_predefined_and_covers_the_whole_app(client):
    data = client.get("/api/uat/checklist").json()
    items = data["items"]
    assert len(items) >= 20
    ids = [i["id"] for i in items]
    assert len(ids) == len(set(ids))
    for item in items:
        assert item["id"] and item["area"] and item["title"]
        assert item["steps"] and item["expected"] and item["launch_url"]
    assert data["results"] == ["pending", "pass", "fail", "blocked"]
    assert data["verdicts"] == ["go", "conditional-go", "no-go"]
    # Whole-app coverage: the big feature areas are all represented.
    for area in ("Login & Access", "Quiz Engine", "Manager Tools",
                 "Developer Tools", "Support", "Global UI"):
        assert area in data["areas"]


# ── Run creation ────────────────────────────────────────────────────────────

def test_create_run_requires_developer(client):
    for role in ("", "manager", "individual_contributor"):
        assert _new_run(client, role=role).status_code == 403


def test_create_run_snapshots_checklist_as_pending(client):
    resp = _new_run(client)
    assert resp.status_code == 200
    run = resp.json()
    assert run["run_id"] == "UAT-0001"
    assert run["status"] == "in_progress"
    assert run["started_by"]["user_id"] == "developer"
    checklist = client.get("/api/uat/checklist").json()["items"]
    assert len(run["items"]) == len(checklist)
    assert all(i["result"] == "pending" and i["note"] == "" for i in run["items"])
    assert run["summary"]["pending"] == run["summary"]["total"] == len(checklist)
    assert run["report"] is None


def test_run_ids_are_sequential(client):
    assert _new_run(client).json()["run_id"] == "UAT-0001"
    assert _new_run(client).json()["run_id"] == "UAT-0002"


# ── Listing / fetching runs ─────────────────────────────────────────────────

def test_run_reads_are_developer_gated(client):
    run_id = _new_run(client).json()["run_id"]
    assert client.get("/api/uat/runs").status_code == 403
    assert client.get("/api/uat/runs?role=manager").status_code == 403
    assert client.get(f"/api/uat/runs/{run_id}?role=individual_contributor").status_code == 403
    assert client.get(f"/api/uat/runs/{run_id}?role=developer").status_code == 200
    assert client.get("/api/uat/runs/UAT-9999?role=developer").status_code == 404


def test_run_list_returns_overviews_newest_first(client):
    _new_run(client)
    _new_run(client)
    data = client.get("/api/uat/runs?role=developer").json()
    assert data["count"] == 2
    assert [r["run_id"] for r in data["runs"]] == ["UAT-0002", "UAT-0001"]
    overview = data["runs"][0]
    assert set(overview) == {"run_id", "status", "started_at", "completed_at",
                             "started_by", "summary", "verdict"}


# ── Marking items ───────────────────────────────────────────────────────────

def test_mark_item_updates_result_note_and_summary(client):
    run_id = _new_run(client).json()["run_id"]

    passed = _mark(client, run_id, "AUTH-01", "pass").json()
    assert passed["item"]["result"] == "pass"
    assert passed["item"]["marked_at"]
    assert passed["summary"]["pass"] == 1

    failed = _mark(client, run_id, "QUIZ-02", "fail", note="Reflection modal never opens.").json()
    assert failed["item"]["note"] == "Reflection modal never opens."
    assert failed["summary"]["fail"] == 1

    # Un-marking back to pending clears marked_at.
    cleared = _mark(client, run_id, "AUTH-01", "pending").json()
    assert cleared["item"]["marked_at"] == ""
    assert cleared["summary"]["pass"] == 0


def test_mark_item_validation_and_gating(client):
    run_id = _new_run(client).json()["run_id"]
    assert _mark(client, run_id, "AUTH-01", "maybe").status_code == 400
    assert _mark(client, run_id, "NOPE-99", "pass").status_code == 404
    assert _mark(client, "UAT-9999", "AUTH-01", "pass").status_code == 404
    assert _mark(client, run_id, "AUTH-01", "pass", role="manager").status_code == 403


# ── Report generation ───────────────────────────────────────────────────────

def test_report_finalizes_run_and_falls_back_without_llm(client, mock_gemini):
    mock_gemini(RuntimeError("LLM unavailable"))
    run = _new_run(client).json()
    for item in run["items"]:
        _mark(client, run["run_id"], item["id"], "pass")
    _mark(client, run["run_id"], "QUIZ-02", "fail", note="Reflection modal never opens.")

    resp = client.post(f"/api/uat/runs/{run['run_id']}/report", json={"role": "developer"})
    assert resp.status_code == 200
    done = resp.json()
    assert done["status"] == "completed"
    assert done["completed_at"]
    report = done["report"]
    assert report["source"] == "fallback"
    assert report["verdict"] == "conditional-go"  # 1 failure out of 22+ checks
    assert report["generated_at"]
    assert any("QUIZ-02" in r for r in report["key_risks"])
    assert report["headline"] and report["summary"] and report["recommendations"]


def test_report_all_pass_is_go_and_unexecuted_run_is_no_go(client, mock_gemini):
    mock_gemini(RuntimeError("LLM unavailable"))

    clean = _new_run(client).json()
    for item in clean["items"]:
        _mark(client, clean["run_id"], item["id"], "pass")
    report = client.post(f"/api/uat/runs/{clean['run_id']}/report",
                         json={"role": "developer"}).json()["report"]
    assert report["verdict"] == "go"

    untouched = _new_run(client).json()
    report = client.post(f"/api/uat/runs/{untouched['run_id']}/report",
                         json={"role": "developer"}).json()["report"]
    assert report["verdict"] == "no-go"


def test_report_uses_llm_when_available(client, mock_gemini):
    mock_gemini(json.dumps({
        "verdict": "conditional-go",
        "headline": "Solid run with one quiz regression.",
        "summary": "The app is close to acceptance; the quiz reflection bug needs a fix.",
        "key_risks": ["QUIZ-02: reflection modal never opens"],
        "recommendations": ["Fix the reflection modal and re-test the quiz area."],
    }))
    run = _new_run(client).json()
    resp = client.post(f"/api/uat/runs/{run['run_id']}/report", json={"role": "developer"})
    report = resp.json()["report"]
    assert report["source"] == "llm"
    assert report["headline"] == "Solid run with one quiz regression."
    assert report["key_risks"] == ["QUIZ-02: reflection modal never opens"]


def test_report_rejects_bad_llm_shape_and_falls_back(client, mock_gemini):
    mock_gemini(json.dumps({"verdict": "ship-it", "headline": "x", "summary": "y",
                            "key_risks": [], "recommendations": []}))
    run = _new_run(client).json()
    report = client.post(f"/api/uat/runs/{run['run_id']}/report",
                         json={"role": "developer"}).json()["report"]
    assert report["source"] == "fallback"
    assert report["verdict"] in ("go", "conditional-go", "no-go")


def test_completed_run_items_are_locked_but_report_can_regenerate(client, mock_gemini):
    mock_gemini(RuntimeError("LLM unavailable"))
    run = _new_run(client).json()
    client.post(f"/api/uat/runs/{run['run_id']}/report", json={"role": "developer"})

    assert _mark(client, run["run_id"], "AUTH-01", "pass").status_code == 400

    again = client.post(f"/api/uat/runs/{run['run_id']}/report", json={"role": "developer"})
    assert again.status_code == 200
    assert again.json()["report"]["generated_at"]


def test_report_requires_developer(client):
    run_id = _new_run(client).json()["run_id"]
    for role in ("", "manager", "individual_contributor"):
        resp = client.post(f"/api/uat/runs/{run_id}/report", json={"role": role})
        assert resp.status_code == 403


# ── Page ────────────────────────────────────────────────────────────────────

def test_qa_console_page_is_served(client):
    assert client.get("/qa-console").status_code == 200
