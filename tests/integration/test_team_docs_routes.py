"""Integration tests for the Team Documentation routes (/api/team-docs).

All writes go to the WAI_DATA_DIR temp dir provided by the conftest client
fixture, so tests never touch the real data/ directory. The AI page-drafting
LLM call is exercised through the mock_gemini fixture (valid JSON for the
LLM path, an Exception for the plain-import fallback path).
"""

import json

from src.core.database import DepartmentScopedStore


def _new_project(client, role="manager", name="Warehouse Move", description="Relocation docs"):
    return client.post("/api/team-docs/projects", json={
        "name": name, "description": description,
        "role": role, "user_id": "manager", "display_name": "Jordan",
    })


def _add_page(client, project_id, role="individual_contributor", **fields):
    body = {"role": role, "user_id": "emp_001", "display_name": "Alex"}
    body.update(fields)
    return client.post(f"/api/team-docs/projects/{project_id}/pages", json=body)


def _seed_vault_upload(with_raw=True):
    """Seed a Knowledge Vault upload the way process_kb_upload_job stores it:
    a raw file plus a {stem}_chunks.json document."""
    store = DepartmentScopedStore("operations")
    if with_raw:
        store.write_raw_document("forklift_rules.txt",
                                 "Forklifts must be inspected daily. Max speed is 8 km/h indoors.")
    store.write_knowledge_document("forklift_rules_chunks", {
        "source_filename": "forklift_rules.txt",
        "department": "operations",
        "chunk_count": 2,
        "uploaded_at": "2026-07-01T00:00:00+00:00",
        "chunks": [
            {"text": "Forklifts must be inspected daily.", "chunk_index": 0},
            {"text": "Max speed is 8 km/h indoors.", "chunk_index": 1},
        ],
    })
    return store


# ── Role gating ──────────────────────────────────────────────────────────────

def test_endpoints_reject_developers_and_anonymous(client):
    for role in ("", "developer", "nonsense"):
        assert _new_project(client, role=role).status_code == 403
        assert client.get(f"/api/team-docs/projects?role={role}").status_code == 403
        assert client.get(f"/api/team-docs/sources?role={role}").status_code == 403


def test_managers_and_employees_can_both_read_and_use_projects(client):
    project_id = _new_project(client, role="manager").json()["project_id"]
    for role in ("manager", "individual_contributor"):
        assert client.get(f"/api/team-docs/projects?role={role}").status_code == 200
        assert client.get(f"/api/team-docs/projects/{project_id}?role={role}").status_code == 200
        assert _add_page(client, project_id, role=role, mode="blank",
                         title=f"Notes by {role}").status_code == 200


def test_project_creation_is_manager_only(client):
    assert _new_project(client, role="manager").status_code == 200
    assert _new_project(client, role="individual_contributor", name="Second").status_code == 403


def test_project_delete_is_manager_only(client):
    project_id = _new_project(client).json()["project_id"]
    resp = client.delete(f"/api/team-docs/projects/{project_id}?role=individual_contributor")
    assert resp.status_code == 403
    assert client.delete(f"/api/team-docs/projects/{project_id}?role=manager").status_code == 200
    assert client.delete("/api/team-docs/projects/PROJ-9999?role=manager").status_code == 404


# ── Project CRUD ─────────────────────────────────────────────────────────────

def test_create_project_shape_and_sequential_ids(client):
    project = _new_project(client).json()
    assert project["project_id"] == "PROJ-0001"
    assert project["name"] == "Warehouse Move"
    assert project["created_by"]["display_name"] == "Jordan"
    assert project["pages"] == []
    assert _new_project(client, name="Second").json()["project_id"] == "PROJ-0002"


def test_create_project_requires_name(client):
    assert _new_project(client, name="   ").status_code == 400


def test_list_projects_returns_overviews(client):
    _new_project(client)
    project_id = _new_project(client, name="Second").json()["project_id"]
    _add_page(client, project_id, mode="blank", title="Kickoff Notes")

    data = client.get("/api/team-docs/projects?role=manager").json()
    assert data["count"] == 2
    # The project touched most recently (page added) sorts first.
    assert data["projects"][0]["project_id"] == project_id
    overview = data["projects"][0]
    assert overview["page_count"] == 1
    assert "pages" not in overview


def test_get_and_patch_project(client):
    project_id = _new_project(client).json()["project_id"]
    assert client.get(f"/api/team-docs/projects/{project_id}?role=manager").status_code == 200
    assert client.get("/api/team-docs/projects/PROJ-9999?role=manager").status_code == 404

    patched = client.patch(f"/api/team-docs/projects/{project_id}", json={
        "role": "individual_contributor", "name": "Renamed", "description": "New desc",
    })
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["description"] == "New desc"

    bad = client.patch(f"/api/team-docs/projects/{project_id}",
                       json={"role": "manager", "name": "  "})
    assert bad.status_code == 400


# ── Vault sources ────────────────────────────────────────────────────────────

def test_sources_lists_only_vault_uploads(client):
    store = _seed_vault_upload()
    # A generated course doc must NOT appear as a source — it isn't an upload.
    store.write_knowledge_document("course_001", {
        "title": "Some Course", "topics": ["x"], "content": "...", "lessons": [],
    })
    data = client.get("/api/team-docs/sources?role=manager").json()
    assert data["count"] == 1
    assert data["sources"][0]["doc_id"] == "forklift_rules_chunks"
    assert data["sources"][0]["filename"] == "forklift_rules.txt"


# ── Pages ────────────────────────────────────────────────────────────────────

def test_blank_page_needs_title_and_gets_starter_content(client):
    project_id = _new_project(client).json()["project_id"]
    assert _add_page(client, project_id, mode="blank", title="").status_code == 400

    data = _add_page(client, project_id, mode="blank", title="Kickoff Notes").json()
    assert data["page_id"] == "page-0001"
    page = data["project"]["pages"][0]
    assert page["title"] == "Kickoff Notes"
    assert page["content"].startswith("# Kickoff Notes")
    assert page["drafted_by"] == "manual"
    assert page["source"] == {"type": "blank"}

    second = _add_page(client, project_id, mode="blank", title="Two").json()
    assert second["page_id"] == "page-0002"


def test_page_mode_and_source_validation(client):
    project_id = _new_project(client).json()["project_id"]
    assert _add_page(client, project_id, mode="magic", title="x").status_code == 400
    assert _add_page(client, project_id, mode="import").status_code == 400  # no source
    assert _add_page(client, project_id, mode="import", source_doc_id="nope").status_code == 404
    assert _add_page(client, "PROJ-9999", mode="blank", title="x").status_code == 404


def test_import_page_uses_raw_document_text(client):
    _seed_vault_upload(with_raw=True)
    project_id = _new_project(client).json()["project_id"]
    data = _add_page(client, project_id, mode="import",
                     source_doc_id="forklift_rules_chunks").json()
    page = data["project"]["pages"][0]
    assert page["title"] == "Forklift Rules"  # prettified from the filename
    assert "inspected daily" in page["content"]
    assert page["drafted_by"] == "import"
    assert page["source"] == {"type": "vault", "doc_id": "forklift_rules_chunks",
                              "filename": "forklift_rules.txt"}


def test_import_page_falls_back_to_chunk_text_without_raw_file(client):
    _seed_vault_upload(with_raw=False)
    project_id = _new_project(client).json()["project_id"]
    data = _add_page(client, project_id, mode="import",
                     source_doc_id="forklift_rules_chunks").json()
    content = data["project"]["pages"][0]["content"]
    assert "inspected daily" in content and "8 km/h" in content


def test_ai_draft_uses_llm_title_and_content(client, mock_gemini):
    _seed_vault_upload()
    mock_gemini(json.dumps({
        "title": "Forklift Safety Rules",
        "content_markdown": "# Forklift Safety Rules\n\n## Daily Checks\n- Inspect before every shift.",
    }))
    project_id = _new_project(client).json()["project_id"]
    page = _add_page(client, project_id, mode="ai_draft",
                     source_doc_id="forklift_rules_chunks").json()["project"]["pages"][0]
    assert page["title"] == "Forklift Safety Rules"
    assert "## Daily Checks" in page["content"]
    assert page["drafted_by"] == "ai"


def test_ai_draft_falls_back_to_import_when_llm_fails(client, mock_gemini):
    _seed_vault_upload()
    mock_gemini(RuntimeError("gemini exploded"))
    project_id = _new_project(client).json()["project_id"]
    page = _add_page(client, project_id, mode="ai_draft",
                     source_doc_id="forklift_rules_chunks").json()["project"]["pages"][0]
    assert page["drafted_by"] == "import"
    assert "inspected daily" in page["content"]
    assert page["title"] == "Forklift Rules"


def test_edit_and_delete_page(client):
    project_id = _new_project(client).json()["project_id"]
    page_id = _add_page(client, project_id, mode="blank", title="Notes").json()["page_id"]

    saved = client.put(f"/api/team-docs/projects/{project_id}/pages/{page_id}", json={
        "role": "individual_contributor", "content": "# Notes\n\nUpdated.", "title": "Meeting Notes",
    })
    assert saved.status_code == 200
    project = client.get(f"/api/team-docs/projects/{project_id}?role=manager").json()
    assert project["pages"][0]["title"] == "Meeting Notes"
    assert project["pages"][0]["content"] == "# Notes\n\nUpdated."

    empty = client.put(f"/api/team-docs/projects/{project_id}/pages/{page_id}",
                       json={"role": "manager", "content": "   "})
    assert empty.status_code == 400
    missing = client.put(f"/api/team-docs/projects/{project_id}/pages/page-9999",
                         json={"role": "manager", "content": "x"})
    assert missing.status_code == 404

    deleted = client.delete(
        f"/api/team-docs/projects/{project_id}/pages/{page_id}?role=individual_contributor")
    assert deleted.status_code == 200
    assert deleted.json()["project"]["pages"] == []


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_txt_and_validation(client):
    project_id = _new_project(client).json()["project_id"]
    empty = client.get(f"/api/team-docs/projects/{project_id}/export?role=manager")
    assert empty.status_code == 404  # no pages yet

    _add_page(client, project_id, mode="blank", title="Alpha")
    _add_page(client, project_id, mode="blank", title="Beta")

    resp = client.get(f"/api/team-docs/projects/{project_id}/export?format=txt&scope=all&role=manager")
    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    text = resp.text
    assert "Alpha" in text and "Beta" in text

    single = client.get(
        f"/api/team-docs/projects/{project_id}/export?format=txt&scope=page-0001&role=manager")
    assert "Alpha" in single.text and "Beta" not in single.text

    assert client.get(
        f"/api/team-docs/projects/{project_id}/export?format=docx&role=manager").status_code == 400
    assert client.get(
        f"/api/team-docs/projects/{project_id}/export?role=developer").status_code == 403


def test_export_pdf_returns_real_pdf(client):
    project_id = _new_project(client).json()["project_id"]
    _add_page(client, project_id, mode="blank", title="Alpha")
    resp = client.get(f"/api/team-docs/projects/{project_id}/export?format=pdf&role=manager")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


# ── Linked sources ───────────────────────────────────────────────────────────

def test_project_starts_with_no_linked_sources(client):
    project = _new_project(client).json()
    assert project["linked_sources"] == []


def test_set_sources_replaces_list_and_validates_and_gates(client):
    _seed_vault_upload()
    project_id = _new_project(client).json()["project_id"]

    resp = client.put(f"/api/team-docs/projects/{project_id}/sources", json={
        "role": "individual_contributor", "source_doc_ids": ["forklift_rules_chunks"],
    })
    assert resp.status_code == 200
    assert resp.json()["linked_sources"] == ["forklift_rules_chunks"]

    # Replacing wholesale with an empty list clears it.
    cleared = client.put(f"/api/team-docs/projects/{project_id}/sources",
                         json={"role": "manager", "source_doc_ids": []})
    assert cleared.json()["linked_sources"] == []

    unknown = client.put(f"/api/team-docs/projects/{project_id}/sources",
                         json={"role": "manager", "source_doc_ids": ["nope"]})
    assert unknown.status_code == 404

    gated = client.put(f"/api/team-docs/projects/{project_id}/sources",
                       json={"role": "developer", "source_doc_ids": []})
    assert gated.status_code == 403

    missing_project = client.put("/api/team-docs/projects/PROJ-9999/sources",
                                 json={"role": "manager", "source_doc_ids": []})
    assert missing_project.status_code == 404


# ── Documentation Master (generate-documentation) ───────────────────────────

def test_generate_documentation_requires_sources(client):
    project_id = _new_project(client).json()["project_id"]
    resp = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                       json={"role": "manager"})
    assert resp.status_code == 400


def test_generate_documentation_requires_team_member_and_known_project(client):
    project_id = _new_project(client).json()["project_id"]
    gated = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                        json={"role": "developer"})
    assert gated.status_code == 403
    missing = client.post("/api/team-docs/projects/PROJ-9999/generate-documentation",
                          json={"role": "manager"})
    assert missing.status_code == 404


def test_generate_documentation_writes_pages_from_llm(client, mock_gemini):
    _seed_vault_upload()
    mock_gemini(json.dumps({
        "pages": [
            {"title": "Warehouse Safety Overview", "content_markdown": "# Warehouse Safety Overview\n\nForklifts are inspected daily."},
            {"title": "Operating Limits", "content_markdown": "# Operating Limits\n\nMax speed is 8 km/h indoors."},
        ],
    }))
    project_id = _new_project(client).json()["project_id"]
    client.put(f"/api/team-docs/projects/{project_id}/sources",
              json={"role": "manager", "source_doc_ids": ["forklift_rules_chunks"]})

    resp = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                       json={"role": "manager"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["pages_written"] == ["Warehouse Safety Overview", "Operating Limits"]
    pages = data["project"]["pages"]
    assert [p["title"] for p in pages] == ["Warehouse Safety Overview", "Operating Limits"]
    assert all(p["drafted_by"] == "ai_synthesis" for p in pages)
    assert pages[0]["source"]["type"] == "vault_synthesis"
    assert pages[0]["source"]["doc_ids"] == ["forklift_rules_chunks"]


def test_generate_documentation_regeneration_replaces_only_synthesis_pages(client, mock_gemini):
    _seed_vault_upload()
    project_id = _new_project(client).json()["project_id"]
    client.put(f"/api/team-docs/projects/{project_id}/sources",
              json={"role": "manager", "source_doc_ids": ["forklift_rules_chunks"]})
    _add_page(client, project_id, mode="blank", title="Manual Notes")

    mock_gemini(json.dumps({"pages": [{"title": "First Pass", "content_markdown": "# First Pass\n\nBody."}]}))
    first = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                        json={"role": "manager"}).json()
    assert [p["title"] for p in first["project"]["pages"]] == ["Manual Notes", "First Pass"]

    mock_gemini(json.dumps({"pages": [{"title": "Second Pass", "content_markdown": "# Second Pass\n\nBody."}]}))
    second = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                         json={"role": "manager"}).json()
    titles = [p["title"] for p in second["project"]["pages"]]
    assert titles == ["Manual Notes", "Second Pass"]  # First Pass replaced, Manual Notes kept


def test_generate_documentation_falls_back_to_error_on_llm_failure(client, mock_gemini):
    _seed_vault_upload()
    mock_gemini(RuntimeError("gemini exploded"))
    project_id = _new_project(client).json()["project_id"]
    client.put(f"/api/team-docs/projects/{project_id}/sources",
              json={"role": "manager", "source_doc_ids": ["forklift_rules_chunks"]})

    resp = client.post(f"/api/team-docs/projects/{project_id}/generate-documentation",
                       json={"role": "manager"})
    assert resp.status_code == 502


# ── Page ─────────────────────────────────────────────────────────────────────

def test_team_documentation_page_is_served(client):
    assert client.get("/team-documentation").status_code == 200
