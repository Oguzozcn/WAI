from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter(tags=["pages"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
PAGES_DIR = PROJECT_ROOT / "frontend" / "pages"

def _serve_page(filename: str) -> HTMLResponse:
    filepath = PAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Page '{filename}' not found")
    return HTMLResponse(content=filepath.read_text(encoding="utf-8"))

@router.get("/", response_class=HTMLResponse)
async def page_dashboard():
    return _serve_page("dashboard.html")

@router.get("/dashboard-chat", response_class=HTMLResponse)
async def page_dashboard_chat():
    return _serve_page("dashboard-chat.html")

@router.get("/learning-path", response_class=HTMLResponse)
async def page_learning_path():
    return _serve_page("learning-path.html")

@router.get("/lesson", response_class=HTMLResponse)
async def page_lesson():
    return _serve_page("lesson.html")

@router.get("/quiz", response_class=HTMLResponse)
async def page_quiz():
    return _serve_page("quiz.html")

@router.get("/quiz-passed", response_class=HTMLResponse)
async def page_quiz_passed():
    return _serve_page("quiz-passed.html")

@router.get("/quiz-retake", response_class=HTMLResponse)
async def page_quiz_retake():
    return _serve_page("quiz-retake.html")

@router.get("/knowledge-vault", response_class=HTMLResponse)
async def page_knowledge_vault():
    return _serve_page("knowledge-vault.html")

@router.get("/chat", response_class=HTMLResponse)
async def page_chat():
    return _serve_page("chat.html")

@router.get("/learning-materials", response_class=HTMLResponse)
async def page_learning_materials():
    return _serve_page("learning-materials.html")

@router.get("/learning-paths-catalog", response_class=HTMLResponse)
async def page_learning_paths_catalog():
    return _serve_page("learning-paths-catalog.html")

@router.get("/manager-dashboard", response_class=HTMLResponse)
async def page_manager_dashboard():
    return _serve_page("manager-dashboard.html")
