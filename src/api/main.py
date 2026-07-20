import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.api.routes import pages, progress, learning_path, quiz, department, knowledge_base, manager, chat, auth, dev_console

app = FastAPI(title="WisdomAI MVP", version="0.1.0")

# Ensure static directories exist to prevent RuntimeError on new environments
js_dir = PROJECT_ROOT / "frontend" / "js"
assets_dir = PROJECT_ROOT / "frontend" / "assets"
js_dir.mkdir(parents=True, exist_ok=True)
assets_dir.mkdir(parents=True, exist_ok=True)

app.mount("/js", StaticFiles(directory=str(js_dir)), name="js")
app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

app.include_router(pages.router)
app.include_router(progress.router)
app.include_router(learning_path.router)
app.include_router(quiz.router)
app.include_router(department.router)
app.include_router(knowledge_base.router)
app.include_router(manager.router)
app.include_router(chat.router)
app.include_router(auth.router)
app.include_router(dev_console.router)
