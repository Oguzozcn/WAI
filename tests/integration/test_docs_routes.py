"""Integration tests for the developer documentation routes (/api/docs).

Editing tests run against a temp docs tree via WAI_DOCS_DIR (same isolation
contract as WAI_DATA_DIR) so they never touch the real docs/ directory. A
read-only integrity test runs against the real repo docs to catch a manifest
that references missing files.
"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    """A minimal, isolated docs tree: 2 sections, 3 pages."""
    docs = tmp_path / "docs"
    (docs / "alpha").mkdir(parents=True)
    (docs / "beta").mkdir(parents=True)
    manifest = {
        "title": "Test Docs",
        "version": 1,
        "sections": [
            {
                "id": "alpha",
                "title": "Alpha",
                "icon": "star",
                "pages": [
                    {"id": "one", "title": "Page One", "file": "alpha/one.md"},
                    {"id": "two", "title": "Page Two", "file": "alpha/two.md"},
                ],
            },
            {
                "id": "beta",
                "title": "Beta",
                "icon": "bolt",
                "pages": [
                    {"id": "three", "title": "Page Three", "file": "beta/three.md"},
                ],
            },
        ],
    }
    (docs / "manifest.json").write_text(json.dumps(manifest))
    (docs / "alpha" / "one.md").write_text("# Page One\n\nHello **world**.\n")
    (docs / "alpha" / "two.md").write_text("# Page Two\n\n- item a\n- item b\n")
    (docs / "beta" / "three.md").write_text("# Page Three\n\n```python\nx = 1\n```\n")
    monkeypatch.setenv("WAI_DOCS_DIR", str(docs))
    return docs


# ── Tree ────────────────────────────────────────────────────────────────────

def test_tree_returns_sections_pages_and_updated_at(client, docs_dir):
    resp = client.get("/api/docs/tree")
    assert resp.status_code == 200
    tree = resp.json()
    assert tree["title"] == "Test Docs"
    assert [s["id"] for s in tree["sections"]] == ["alpha", "beta"]
    page = tree["sections"][0]["pages"][0]
    assert page["id"] == "one"
    assert page["updated_at"]  # mtime of an existing file is non-empty


# ── Read a page ─────────────────────────────────────────────────────────────

def test_get_page_returns_markdown_content(client, docs_dir):
    resp = client.get("/api/docs/page/alpha/one")
    assert resp.status_code == 200
    body = resp.json()
    assert body["section_title"] == "Alpha"
    assert body["title"] == "Page One"
    assert "Hello **world**" in body["content"]


def test_get_unknown_page_is_404(client, docs_dir):
    assert client.get("/api/docs/page/alpha/nope").status_code == 404
    assert client.get("/api/docs/page/nope/one").status_code == 404


def test_page_ids_cannot_traverse_paths(client, docs_dir):
    # Ids are looked up in the manifest, never used as raw paths.
    resp = client.get("/api/docs/page/..%2F..%2Fetc/passwd")
    assert resp.status_code == 404


# ── Save a page ─────────────────────────────────────────────────────────────

def test_save_requires_developer_role(client, docs_dir):
    for role in ("", "manager", "individual_contributor"):
        resp = client.put(
            "/api/docs/page/alpha/one",
            json={"content": "# Nope", "role": role},
        )
        assert resp.status_code == 403
    # File untouched
    assert "Hello" in (docs_dir / "alpha" / "one.md").read_text()


def test_save_as_developer_persists(client, docs_dir):
    new_content = "# Page One\n\nUpdated by test.\n"
    resp = client.put(
        "/api/docs/page/alpha/one",
        json={"content": new_content, "role": "developer"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"
    assert (docs_dir / "alpha" / "one.md").read_text() == new_content
    # Round-trips through the read endpoint
    assert client.get("/api/docs/page/alpha/one").json()["content"] == new_content


def test_save_empty_content_is_rejected(client, docs_dir):
    resp = client.put(
        "/api/docs/page/alpha/one",
        json={"content": "   \n  ", "role": "developer"},
    )
    assert resp.status_code == 400


# ── Export ──────────────────────────────────────────────────────────────────

def test_export_txt_single_page(client, docs_dir):
    resp = client.get("/api/docs/export?format=txt&scope=alpha/one")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert 'attachment; filename="wisdomai-docs-alpha-one.txt"' in resp.headers["content-disposition"]
    assert "Hello **world**" in resp.text


def test_export_txt_all_concatenates_every_page(client, docs_dir):
    resp = client.get("/api/docs/export?format=txt&scope=all")
    assert resp.status_code == 200
    for marker in ("Page One", "Page Two", "Page Three", "ALPHA", "BETA"):
        assert marker in resp.text


def test_export_pdf_returns_real_pdf(client, docs_dir):
    for scope in ("alpha/one", "all"):
        resp = client.get(f"/api/docs/export?format=pdf&scope={scope}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content[:5] == b"%PDF-"


def test_export_rejects_bad_format_and_scope(client, docs_dir):
    assert client.get("/api/docs/export?format=docx&scope=all").status_code == 400
    assert client.get("/api/docs/export?format=txt&scope=not-a-scope").status_code == 400
    assert client.get("/api/docs/export?format=txt&scope=alpha/nope").status_code == 404


# ── Real repo docs integrity (read-only, no WAI_DOCS_DIR override) ─────────

def test_repo_manifest_files_all_exist_and_are_titled(client):
    docs_root = PROJECT_ROOT / "docs"
    manifest = json.loads((docs_root / "manifest.json").read_text())
    assert manifest["sections"], "repo manifest has no sections"
    for section in manifest["sections"]:
        assert section["id"] and section["title"] and section["icon"]
        assert section["pages"], f"section {section['id']} has no pages"
        for page in section["pages"]:
            filepath = docs_root / page["file"]
            assert filepath.exists(), f"manifest references missing file {page['file']}"
            first_line = filepath.read_text(encoding="utf-8").lstrip().splitlines()[0]
            assert first_line.startswith("# "), f"{page['file']} must start with an H1 title"
