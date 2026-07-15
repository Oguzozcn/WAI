import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.routes import pages, progress, learning_path, quiz, department, knowledge_base

app = FastAPI(title="WisdomAI MVP", version="0.1.0")

app.mount("/js", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "js")), name="js")
app.mount("/assets", StaticFiles(directory=str(PROJECT_ROOT / "frontend" / "assets")), name="assets")

app.include_router(pages.router)
app.include_router(progress.router)
app.include_router(learning_path.router)
app.include_router(quiz.router)
app.include_router(department.router)
app.include_router(knowledge_base.router)
