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

@router.get("/login", response_class=HTMLResponse)
async def page_login():
    return _serve_page("login.html")

@router.get("/", response_class=HTMLResponse)
async def page_dashboard():
    return _serve_page("dashboard.html")

@router.get("/learning-path", response_class=HTMLResponse)
async def page_learning_path():
    return _serve_page("learning-path.html")

@router.get("/lesson", response_class=HTMLResponse)
async def page_lesson():
    return _serve_page("lesson.html")

@router.get("/quiz", response_class=HTMLResponse)
async def page_quiz():
    return _serve_page("quiz.html")

@router.get("/knowledge-vault", response_class=HTMLResponse)
async def page_knowledge_vault():
    return _serve_page("knowledge-vault.html")

@router.get("/chat", response_class=HTMLResponse)
async def page_chat():
    return _serve_page("chat.html")

@router.get("/learning-materials", response_class=HTMLResponse)
async def page_learning_materials():
    return _serve_page("learning-materials.html")

@router.get("/learning-paths", response_class=HTMLResponse)
async def page_learning_paths():
    return _serve_page("learning-paths.html")

@router.get("/edit-learning-path", response_class=HTMLResponse)
async def page_edit_learning_path():
    return _serve_page("edit-learning-path.html")

@router.get("/catalog", response_class=HTMLResponse)
async def page_catalog():
    return _serve_page("catalog.html")

@router.get("/manager-dashboard", response_class=HTMLResponse)
async def page_manager_dashboard():
    return _serve_page("manager-dashboard.html")

@router.get("/dev-console", response_class=HTMLResponse)
async def page_dev_console():
    return _serve_page("dev-console.html")

@router.get("/settings", response_class=HTMLResponse)
async def page_settings():
    return _serve_page("settings.html")

@router.get("/profile", response_class=HTMLResponse)
async def page_profile():
    return _serve_page("profile.html")

# NOTE: "/documentation", not "/docs" — FastAPI's built-in Swagger UI owns /docs.
@router.get("/documentation", response_class=HTMLResponse)
async def page_documentation():
    return _serve_page("documentation.html")

@router.get("/support", response_class=HTMLResponse)
async def page_support():
    return _serve_page("support.html")

@router.get("/support-console", response_class=HTMLResponse)
async def page_support_console():
    return _serve_page("support-console.html")

@router.get("/qa-console", response_class=HTMLResponse)
async def page_qa_console():
    return _serve_page("qa-console.html")

@router.get("/team-documentation", response_class=HTMLResponse)
async def page_team_documentation():
    return _serve_page("team-documentation.html")
