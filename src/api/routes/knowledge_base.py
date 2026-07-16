import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from pathlib import Path
from src.services.curriculum_service import (
    identify_content_gaps,
    recursive_character_splitter,
    trigger_curriculum_generation,
)
from WAI_agent.shared.persistence import DepartmentScopedStore
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT

router = APIRouter(prefix="/api/kb", tags=["knowledge_base"])

ALLOWED_EXTENSIONS = {".txt", ".md"}

@router.get("/documents")
async def api_kb_documents(department: str = DEFAULT_DEPARTMENT):
    """List all knowledge base documents."""
    store = DepartmentScopedStore(department)
    docs = store.read_knowledge_base()
    return {"documents": docs, "count": len(docs)}

class ValidateDocumentRequest(BaseModel):
    document_content: str

@router.post("/validate")
async def api_kb_validate(body: ValidateDocumentRequest, department: str = DEFAULT_DEPARTMENT):
    """Validate a document against the knowledge base."""
    result = identify_content_gaps(
        document_content=body.document_content,
        department=department,
    )
    return result

@router.post("/upload")
async def api_kb_upload(
    file: UploadFile = File(...),
    department: str = Form(DEFAULT_DEPARTMENT),
    append_to_latest: bool = Form(False)
):
    """Upload a document through the full ingestion pipeline.

    Pipeline stages:
      1. Parse  — read and decode the uploaded file.
      2. Validate — run the KB Validator to check for contradictions.
      3. Chunk  — split the approved text into overlapping chunks.
      4. Enrich — attach metadata (filename, department, timestamp) to each chunk.
      5. Save   — persist chunks to the knowledge base store.

    Returns 409 Conflict if the KB Validator rejects the document.
    """
    # ── Stage 1: Parse ──────────────────────────────────────────────────────
    # Narrow file.filename (str | None) immediately so the rest of the function
    # can use the typed `filename: str` variable without repeated None checks.
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename.")
    filename: str = file.filename

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Only .txt and .md files are supported in the MVP."
        )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File could not be read as UTF-8 text.")

    if not content.strip():
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # ── Stage 2: Validate ────────────────────────────────────────────────────
    # Call the KB Validator by invoking the agent's underlying tool directly.
    # The ADK sub-agent is designed for conversational use; for the API pipeline
    # we call `identify_content_gaps` and perform a lightweight structural check
    # to decide APPROVED vs REJECTED without a full agent round-trip overhead.
    gap_analysis = identify_content_gaps(
        document_content=content,
        department=department,
    )

    # Detect HIGH-severity findings that should block the upload.
    high_severity_findings = [
        f for f in gap_analysis.get("findings", [])
        if f.get("severity") == "high"
    ]

    if high_severity_findings:
        # Build a rejection payload that mirrors the KB Validator JSON contract.
        contradictions = [
            {
                "conflict_id": f"c{i + 1:03d}",
                "severity": finding.get("severity", "high"),
                "field": finding.get("type", "unknown"),
                "existing_value": "See existing knowledge base",
                "new_value": finding.get("description", ""),
                "document_references": [filename],
                "recommended_action": finding.get("description", "Resolve conflict before re-uploading."),
            }
            for i, finding in enumerate(high_severity_findings)
        ]
        raise HTTPException(
            status_code=409,
            detail={
                "status": "REJECTED",
                "confidence_score": 0.95,
                "contradictions": contradictions,
                "summary": (
                    f"The document '{filename}' was rejected by the Knowledge Base Validator. "
                    f"{len(contradictions)} conflict(s) detected. Resolve them before re-uploading."
                ),
            },
        )

    # ── Stage 3: Chunk ────────────────────────────────────────────────────────
    chunks = recursive_character_splitter(content, max_tokens=1024, overlap=200)

    # ── Stage 4: Enrich Metadata ─────────────────────────────────────────────
    upload_timestamp = datetime.now(timezone.utc).isoformat()
    enriched_chunks = [
        {
            **chunk,
            "source_filename": filename,
            "department": department,
            "uploaded_at": upload_timestamp,
        }
        for chunk in chunks
    ]

    # ── Stage 5: Save ──────────────────────────────────────────────────────────
    store = DepartmentScopedStore(department)
    store.write_raw_document(filename, content)
    store.write_catalog_input(filename, content)



    # Persist the enriched chunks alongside the raw document so retrieval
    # pipelines can use fine-grained, overlapping text segments.
    chunks_key = f"{Path(filename).stem}_chunks"
    store.write_knowledge_document(
        chunks_key,
        {
            "source_filename": filename,
            "department": department,
            "chunk_count": len(enriched_chunks),
            "uploaded_at": upload_timestamp,
            "chunks": enriched_chunks,
        },
    )

    return {
        "status": "success",
        "message": f"File '{filename}' validated, chunked, and saved successfully.",
        "filename": filename,
        "chunk_count": len(enriched_chunks),
        "validation": {
            "status": "APPROVED",
            "findings_count": len(gap_analysis.get("findings", [])),
        },

    }


class GenerateFromInputRequest(BaseModel):
    filename: str
    department: str = DEFAULT_DEPARTMENT
    append_to_latest: bool = False

@router.post("/generate-from-input")
async def api_generate_from_input(req: GenerateFromInputRequest):
    """Generate a curriculum from an existing file in the catalog/inputs directory."""
    store = DepartmentScopedStore(req.department)
    
    inputs = store.list_catalog_inputs()
    if not any(f["filename"] == req.filename for f in inputs):
        raise HTTPException(status_code=404, detail=f"File {req.filename} not found in catalog inputs.")
    
    result = trigger_curriculum_generation(
        filename=req.filename,
        department=req.department,
        append_to_latest=req.append_to_latest,
    )
    
    if result.get("status") != "success":
        raise HTTPException(status_code=500, detail=result.get("message", "Curriculum generation failed."))

    if result.get("path_id"):
        path_data = store.read_learning_path(result["path_id"])
        if path_data:
            path_data["source_input_files"] = [req.filename]
            store.write_standard_path(result["path_id"], path_data)

    return result

@router.get("/catalog/inputs")
async def api_catalog_inputs(department: str = DEFAULT_DEPARTMENT):
    """List all input files (uploaded learning materials) in the catalog."""
    store = DepartmentScopedStore(department)
    inputs = store.list_catalog_inputs()
    return {"inputs": inputs, "count": len(inputs)}

@router.get("/catalog/learning-paths")
async def api_catalog_learning_paths(
    department: str = DEFAULT_DEPARTMENT,
    user_id: str | None = None,
):
    """List all learning paths (official + unofficial) from the catalog."""
    store = DepartmentScopedStore(department)
    official = store.list_standard_paths()
    unofficial = store.list_unofficial_paths(user_id=user_id)
    all_paths = official + unofficial
    return {
        "learning_paths": all_paths,
        "count": len(all_paths),
        "official_count": len(official),
        "unofficial_count": len(unofficial),
    }
