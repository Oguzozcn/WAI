"""Unit tests for the KB ingestion pipeline in curriculum_service.

All storage-touching tests rely on the ``test_data_dir`` fixture, which sets
WAI_DATA_DIR so that ``DepartmentScopedStore("operations")`` (constructed with
no explicit base_path) resolves to an isolated temp directory.
"""

from src.core.database import DepartmentScopedStore
from src.services.curriculum_service import (
    recursive_character_splitter,
    identify_content_gaps,
    process_kb_upload_job,
)


# ── recursive_character_splitter ─────────────────────────────────────────────

def test_splitter_empty_returns_empty_list():
    assert recursive_character_splitter("") == []
    assert recursive_character_splitter("   \n  ") == []


def test_splitter_short_string_single_chunk():
    chunks = recursive_character_splitter("Hello world.", max_tokens=1024, overlap=200)
    assert len(chunks) == 1
    assert chunks[0]["char_start"] == 0
    assert chunks[0]["text"] == "Hello world."
    assert chunks[0]["chunk_index"] == 0


def test_splitter_long_string_multiple_chunks_are_contiguous_within_overlap():
    text = "Alpha beta gamma delta epsilon. " * 20
    overlap = 20
    chunks = recursive_character_splitter(text, max_tokens=60, overlap=overlap)

    assert len(chunks) > 1
    assert chunks[0]["char_start"] == 0

    # Consecutive chunks tile the source: the next chunk starts no later than the
    # previous chunk's end, and no earlier than (end - overlap). This is the real
    # invariant the implementation guarantees ("overlap" window between chunks).
    for i in range(len(chunks) - 1):
        end_n = chunks[i]["char_end"]
        start_next = chunks[i + 1]["char_start"]
        assert start_next <= end_n
        assert start_next >= end_n - overlap


# ── identify_content_gaps ────────────────────────────────────────────────────

def test_identify_gaps_short_document_flagged_high_gap(test_data_dir):
    result = identify_content_gaps("Too short.", department="operations")
    findings = result["findings"]
    assert any(
        f["type"] == "gap" and f["severity"] == "high" for f in findings
    )


def test_identify_gaps_detects_conflict_with_overlapping_concepts(test_data_dir):
    store = DepartmentScopedStore("operations")
    store.write_knowledge_document(
        "existing_doc",
        {
            "title": "Existing Operations Doc",
            "topics": ["Alpha Concept", "Beta Concept", "Gamma Concept"],
            "content": "Reference material.",
        },
    )

    # Bold-markdown terms are what _extract_key_concepts picks up.
    doc = (
        "This training document explains **Alpha Concept** and **Beta Concept** "
        "in detail so operators can follow the standard procedures correctly here."
    )
    result = identify_content_gaps(doc, department="operations")

    conflicts = [f for f in result["findings"] if f["type"] == "conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["existing_doc_title"] == "Existing Operations Doc"


def test_identify_gaps_no_conflict_for_unrelated_content(test_data_dir):
    store = DepartmentScopedStore("operations")
    store.write_knowledge_document(
        "existing_doc",
        {
            "title": "Existing Operations Doc",
            "topics": ["Alpha Concept", "Beta Concept", "Gamma Concept"],
            "content": "Reference material.",
        },
    )

    doc = (
        "This unrelated note discusses **Zebra Topic** and **Yak Topic** which "
        "share nothing with the existing knowledge base entries at all whatsoever."
    )
    result = identify_content_gaps(doc, department="operations")

    conflicts = [f for f in result["findings"] if f["type"] == "conflict"]
    assert conflicts == []


# ── process_kb_upload_job ────────────────────────────────────────────────────

def test_process_kb_upload_job_completed(test_data_dir):
    store = DepartmentScopedStore("operations")
    content = (
        "This is a sufficiently long knowledge base document about warehouse "
        "operations, safety checklists, and daily standard procedures for the "
        "operations team to follow during the transition period every single day."
    )
    process_kb_upload_job("job_ok", "handbook.txt", content, "operations")

    job = store.read_kb_job("job_ok")
    assert job is not None
    assert job["status"] == "completed"


def test_process_kb_upload_job_flagged_on_conflict(test_data_dir):
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
        "This new document restates **Alpha Concept** and **Beta Concept** across "
        "several paragraphs, overlapping heavily with the material already stored "
        "in the operations knowledge base and therefore should be flagged for review."
    )
    process_kb_upload_job("job_conflict", "overlap.txt", content, "operations")

    job = store.read_kb_job("job_conflict")
    assert job is not None
    assert job["status"] == "flagged"

    pending = store.read_conflicts(status="pending")
    assert len(pending) >= 1


# ── KB job + duplicate/versioning storage helpers ────────────────────────────

def test_kb_job_round_trip(test_data_dir):
    store = DepartmentScopedStore("operations")
    store.write_kb_job("job_rt", {"job_id": "job_rt", "status": "pending"})
    job = store.read_kb_job("job_rt")
    assert job["job_id"] == "job_rt"
    assert job["status"] == "pending"
    assert store.read_kb_job("does_not_exist") is None


def test_raw_document_versioning(test_data_dir):
    store = DepartmentScopedStore("operations")

    # Before any file exists, the first version candidate is _v2.
    assert store.raw_document_exists("doc.txt") is False
    assert store.next_version_filename("doc.txt") == "doc_v2.txt"

    store.write_raw_document("doc.txt", "original content")
    assert store.raw_document_exists("doc.txt") is True
    assert store.next_version_filename("doc.txt") == "doc_v2.txt"

    # With doc_v2.txt also present, the next candidate rolls to _v3.
    store.write_raw_document("doc_v2.txt", "second version")
    assert store.next_version_filename("doc.txt") == "doc_v3.txt"
