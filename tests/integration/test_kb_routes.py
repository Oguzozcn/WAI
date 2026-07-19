"""Integration tests for the /api/kb routes via FastAPI TestClient.

FastAPI's TestClient runs BackgroundTasks synchronously before the response is
returned, so an upload's processing job is already finished by the time the
upload response arrives. We still poll defensively with a small attempt cap.
"""

from src.core.database import DepartmentScopedStore


def _poll_job(client, job_id, department="operations", attempts=10):
    job = None
    for _ in range(attempts):
        resp = client.get(f"/api/kb/upload/status/{job_id}?department={department}")
        assert resp.status_code == 200
        job = resp.json()
        if job["status"] in ("completed", "flagged", "error"):
            return job
    return job


def test_upload_txt_processes_and_completes(client):
    content = (
        b"This is a suitably long standalone operations knowledge document that "
        b"describes daily standard procedures, safety steps, and handover routines "
        b"for the operations team without overlapping any existing catalog entry."
    )
    resp = client.post(
        "/api/kb/upload",
        files={"file": ("test.txt", content, "text/plain")},
        data={"department": "operations"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "processing"
    assert "job_id" in body

    job = _poll_job(client, body["job_id"])
    assert job["status"] == "completed"


def test_conflict_resolve_rejected_retracts_files(client, test_data_dir):
    # Seed an existing doc so the upload's concepts overlap → conflict → flagged.
    store = DepartmentScopedStore("operations")
    store.write_knowledge_document(
        "existing_doc",
        {
            "title": "Existing Operations Doc",
            "topics": ["Alpha Concept", "Beta Concept", "Gamma Concept"],
            "content": "Reference material.",
        },
    )

    content = (
        b"This new operations note restates **Alpha Concept** and **Beta Concept** "
        b"across multiple paragraphs and therefore overlaps heavily with the "
        b"existing knowledge base document, so it must be flagged for manual review."
    )
    up = client.post(
        "/api/kb/upload",
        files={"file": ("conflicting.txt", content, "text/plain")},
        data={"department": "operations"},
    )
    assert up.status_code == 200
    job = _poll_job(client, up.json()["job_id"])
    assert job["status"] == "flagged"

    # The raw + catalog files exist on disk before resolution.
    assert (store.raw_documents_path / "conflicting.txt").exists()
    assert (store.catalog_inputs_path / "conflicting.txt").exists()

    conflicts = client.get("/api/kb/conflicts?status=pending&department=operations").json()
    assert conflicts["count"] >= 1
    conflict_id = conflicts["conflicts"][0]["conflict_id"]

    resolved = client.post(
        f"/api/kb/conflicts/{conflict_id}/resolve",
        json={"resolution": "rejected", "department": "operations"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "dismissed"

    # Rejected resolution retracts the saved raw + catalog files.
    assert not (store.raw_documents_path / "conflicting.txt").exists()
    assert not (store.catalog_inputs_path / "conflicting.txt").exists()


def test_duplicate_filename_then_new_version(client):
    store = DepartmentScopedStore("operations")
    content = (
        b"This is a long enough operations document about routine daily handover "
        b"procedures and safety checks that will be saved into the knowledge base."
    )

    # First upload succeeds and (via background task) writes dup.txt.
    first = client.post(
        "/api/kb/upload",
        files={"file": ("dup.txt", content, "text/plain")},
        data={"department": "operations"},
    )
    assert first.status_code == 200
    _poll_job(client, first.json()["job_id"])
    assert store.raw_document_exists("dup.txt")

    # Same filename, no version_action → duplicate response.
    second = client.post(
        "/api/kb/upload",
        files={"file": ("dup.txt", content, "text/plain")},
        data={"department": "operations"},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"

    # Re-upload requesting a new version → a versioned file is created.
    third = client.post(
        "/api/kb/upload",
        files={"file": ("dup.txt", content, "text/plain")},
        data={"department": "operations", "version_action": "new_version"},
    )
    assert third.status_code == 200
    _poll_job(client, third.json()["job_id"])
    assert (store.raw_documents_path / "dup_v2.txt").exists()
