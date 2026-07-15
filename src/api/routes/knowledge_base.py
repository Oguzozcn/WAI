from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from pathlib import Path
from src.services.curriculum_service import identify_content_gaps, trigger_curriculum_generation
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
    """Upload a document file, save it to raw/, and generate a curriculum."""
    ext = Path(file.filename).suffix.lower() if file.filename else ""
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

    store = DepartmentScopedStore(department)
    store.write_raw_document(file.filename, content)
    store.write_catalog_input(file.filename, content)

    return {"status": "success", "message": f"File {file.filename} uploaded successfully.", "filename": file.filename}

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
