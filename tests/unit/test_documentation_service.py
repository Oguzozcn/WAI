"""Unit tests for src.services.documentation_service's internal helpers.

The full generate_project_documentation flow (success, regeneration replacing
only ai_synthesis pages, no_sources/not_found/error statuses) is already
exercised end-to-end via the /api/team-docs route tests in
tests/integration/test_team_docs_routes.py. These tests cover what that
integration suite doesn't reach directly: how a linked source resolves to
either plain text or a native binary media Part depending on its file type,
and the title-cleaning helper's length cap.
"""

from src.core.database import DepartmentScopedStore
from src.services.documentation_service import _clean_title, _resolve_source


def test_resolve_source_text_upload_returns_raw_text(test_data_dir):
    store = DepartmentScopedStore("operations")
    store.write_raw_document("glossary.txt", "SLA: Service Level Agreement.")
    store.write_knowledge_document("glossary_chunks", {
        "source_filename": "glossary.txt",
        "chunks": [{"text": "SLA: Service Level Agreement.", "chunk_index": 0}],
    })

    source = _resolve_source(store, "glossary_chunks")
    assert source["kind"] == "text"
    assert source["filename"] == "glossary.txt"
    assert "Service Level Agreement" in source["text"]


def test_resolve_source_binary_upload_returns_native_media_part(test_data_dir):
    store = DepartmentScopedStore("operations")
    store.write_raw_document_bytes("walkthrough.mp4", b"fake mp4 bytes")
    store.write_knowledge_document("walkthrough_chunks", {
        "source_filename": "walkthrough.mp4",
        "topics": ["onboarding"],
        "chunks": [{"text": "A one-paragraph summary of the video.", "chunk_index": 0}],
    })

    source = _resolve_source(store, "walkthrough_chunks")
    assert source["kind"] == "media"
    assert source["filename"] == "walkthrough.mp4"
    assert source["part"].inline_data.mime_type == "video/mp4"
    assert source["part"].inline_data.data == b"fake mp4 bytes"


def test_resolve_source_returns_none_for_unknown_or_incomplete_doc(test_data_dir):
    store = DepartmentScopedStore("operations")
    assert _resolve_source(store, "does_not_exist") is None

    store.write_knowledge_document("no_filename_doc", {"chunks": []})
    assert _resolve_source(store, "no_filename_doc") is None


def test_clean_title_caps_length_with_ellipsis():
    long_title = "Word " * 40
    cleaned = _clean_title(long_title, max_len=80)
    assert len(cleaned) <= 81
    assert cleaned.endswith("…")


def test_clean_title_rejects_non_strings_and_blanks():
    assert _clean_title(None) == ""
    assert _clean_title(123) == ""
    assert _clean_title("   ") == ""
    assert _clean_title("  Onboarding Guide  ") == "Onboarding Guide"
