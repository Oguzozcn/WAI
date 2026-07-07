"""
WisdomAI MVP — FastAPI Server
================================
Serves the Stitch UI pages and exposes REST API endpoints
that call WAI_agent tools directly.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── Ensure WAI_agent is importable ──
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from WAI_agent.tools.quiz_tools import (
    generate_quiz,
    evaluate_answers,
    generate_reflection_prompt,
    generate_gap_review,
)
from WAI_agent.tools.curriculum_tools import (
    generate_learning_path,
    generate_daily_agenda,
    identify_content_gaps,
)
from WAI_agent.tools.progress_tools import (
    get_user_progress,
    update_progress,
    get_department_readiness,
    flag_at_risk_users,
)
from WAI_agent.shared.persistence import DepartmentScopedStore
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT


# ── App ──
app = FastAPI(title="WisdomAI MVP", version="0.1.0")

# Mount JS files as static
app.mount("/js", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "js")), name="js")
app.mount("/assets", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "assets")), name="assets")

PAGES_DIR = PROJECT_ROOT / "frontend" / "pages"


# ═══════════════════════════════════════════
# PAGE ROUTES — serve Stitch HTML pages
# ═══════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def page_dashboard():
    return _serve_page("dashboard.html")


@app.get("/dashboard-chat", response_class=HTMLResponse)
async def page_dashboard_chat():
    return _serve_page("dashboard-chat.html")


@app.get("/learning-path", response_class=HTMLResponse)
async def page_learning_path():
    return _serve_page("learning-path.html")


@app.get("/lesson", response_class=HTMLResponse)
async def page_lesson():
    return _serve_page("lesson.html")


@app.get("/quiz", response_class=HTMLResponse)
async def page_quiz():
    return _serve_page("quiz.html")


@app.get("/quiz-passed", response_class=HTMLResponse)
async def page_quiz_passed():
    return _serve_page("quiz-passed.html")


@app.get("/quiz-retake", response_class=HTMLResponse)
async def page_quiz_retake():
    return _serve_page("quiz-retake.html")


@app.get("/knowledge-vault", response_class=HTMLResponse)
async def page_knowledge_vault():
    return _serve_page("knowledge-vault.html")


@app.get("/chat", response_class=HTMLResponse)
async def page_chat():
    return _serve_page("chat.html")


def _serve_page(filename: str) -> HTMLResponse:
    """Read and return an HTML page from the frontend/pages directory."""
    filepath = PAGES_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Page '{filename}' not found")
    return HTMLResponse(content=filepath.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════
# API ROUTES — structured data endpoints
# ═══════════════════════════════════════════

# ── User Progress ──

@app.get("/api/user/{user_id}/progress")
async def api_get_progress(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Get user progress data for the dashboard."""
    result = get_user_progress(user_id=user_id, department=department)
    return result


class ProgressUpdateRequest(BaseModel):
    event_type: str
    event_data: dict = {}


@app.post("/api/user/{user_id}/progress")
async def api_update_progress(user_id: str, body: ProgressUpdateRequest, department: str = DEFAULT_DEPARTMENT):
    """Update user progress with a new event."""
    result = update_progress(
        user_id=user_id,
        event_type=body.event_type,
        event_data=body.event_data,
        department=department,
    )
    return result


# ── Learning Path ──

@app.get("/api/user/{user_id}/learning-path")
async def api_get_learning_path(user_id: str, role: str = "new_joiner", department: str = DEFAULT_DEPARTMENT):
    """Generate a learning path for the user."""
    result = generate_learning_path(role=role, department=department)
    return result


@app.get("/api/user/{user_id}/daily-agenda")
async def api_get_daily_agenda(user_id: str, day: int = 1, department: str = DEFAULT_DEPARTMENT):
    """Generate a daily training agenda."""
    # Use user_id as a proxy for learning_path_id in MVP
    result = generate_daily_agenda(
        learning_path_id=f"lp_{user_id}",
        day_number=day,
        department=department,
    )
    return result


# ── Quiz ──

class QuizGenerateRequest(BaseModel):
    topic: str
    difficulty: str = "medium"
    question_count: int = 5
    quiz_type: str = "short_quiz"


@app.post("/api/quiz/generate")
async def api_generate_quiz(body: QuizGenerateRequest, department: str = DEFAULT_DEPARTMENT):
    """Generate a quiz on a topic."""
    result = generate_quiz(
        topic=body.topic,
        difficulty=body.difficulty,
        question_count=body.question_count,
        quiz_type=body.quiz_type,
        department=department,
    )
    return result


class QuizEvaluateRequest(BaseModel):
    quiz_id: str
    user_id: str
    answers: list[dict]


@app.post("/api/quiz/evaluate")
async def api_evaluate_quiz(body: QuizEvaluateRequest, department: str = DEFAULT_DEPARTMENT):
    """Evaluate user answers for a quiz."""
    result = evaluate_answers(
        quiz_id=body.quiz_id,
        user_id=body.user_id,
        answers=body.answers,
        department=department,
    )
    return result


class ReflectionRequest(BaseModel):
    question_id: str
    question_text: str
    user_answer: str
    correct_answer: str
    concept_tags: list[str] = []


@app.post("/api/quiz/reflection")
async def api_reflection(body: ReflectionRequest):
    """Generate a metacognitive reflection prompt."""
    result = generate_reflection_prompt(
        question_id=body.question_id,
        question_text=body.question_text,
        user_answer=body.user_answer,
        correct_answer=body.correct_answer,
        concept_tags=body.concept_tags,
    )
    return result


# ── Gap Review ──

@app.get("/api/user/{user_id}/gap-review")
async def api_gap_review(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Generate a spaced-repetition gap review."""
    result = generate_gap_review(user_id=user_id, department=department)
    return result


# ── Department ──

@app.get("/api/department/readiness")
async def api_department_readiness(department: str = DEFAULT_DEPARTMENT):
    """Get department-level readiness metrics."""
    result = get_department_readiness(department=department)
    return result


@app.get("/api/department/at-risk")
async def api_at_risk(department: str = DEFAULT_DEPARTMENT):
    """Get at-risk users for a department."""
    result = flag_at_risk_users(department=department)
    return result


# ── Knowledge Base ──

@app.get("/api/kb/documents")
async def api_kb_documents(department: str = DEFAULT_DEPARTMENT):
    """List all knowledge base documents."""
    store = DepartmentScopedStore(department)
    docs = store.read_knowledge_base()
    return {"documents": docs, "count": len(docs)}


class ValidateDocumentRequest(BaseModel):
    document_content: str


@app.post("/api/kb/validate")
async def api_kb_validate(body: ValidateDocumentRequest, department: str = DEFAULT_DEPARTMENT):
    """Validate a document against the knowledge base."""
    result = identify_content_gaps(
        document_content=body.document_content,
        department=department,
    )
    return result


# ═══════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
