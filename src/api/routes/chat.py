"""Chat API Route.

Wires the ADK ``root_agent`` into the live app via a Runner + in-memory
session service. Each department-scoped user gets one persistent conversation
session (seeded with their user_progress so the LuckEliminationHook can enforce
policy). Session state is in-memory only — no persistent chat history.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from google.genai import types
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from src.agents.agent import build_root_agent
from src.core.database import DepartmentScopedStore
from src.core.config import DEFAULT_DEPARTMENT

router = APIRouter(prefix="/api/chat", tags=["chat"])

_APP_NAME = "wisdomai"
_session_service = InMemorySessionService()
_known_sessions: set[str] = set()


def _get_runner() -> Runner:
    """Build a fresh Runner bound to a freshly-built root_agent on every call.

    This is what makes Agent Console edits (orchestrator instruction/model,
    skill personas) apply immediately with no server restart — the session
    service itself (chat history/state) stays the persistent module-level
    singleton above, only the agent + runner are rebuilt.
    """
    return Runner(agent=build_root_agent(), session_service=_session_service, app_name=_APP_NAME)


class ChatRequest(BaseModel):
    user_id: str
    message: str
    department: str = DEFAULT_DEPARTMENT


@router.post("")
async def chat(req: ChatRequest):
    session_id = f"{req.department}:{req.user_id}"

    if session_id not in _known_sessions:
        store = DepartmentScopedStore(req.department)
        user_progress = store.read_user_progress(req.user_id) or {}
        await _session_service.create_session(
            app_name=_APP_NAME,
            user_id=req.user_id,
            session_id=session_id,
            state={"user_progress": user_progress},
        )
        _known_sessions.add(session_id)

    content = types.Content(role="user", parts=[types.Part(text=req.message)])

    try:
        final_text = ""
        async for event in _get_runner().run_async(
            user_id=req.user_id,
            session_id=session_id,
            new_message=content,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = event.content.parts[0].text or ""
        if not final_text:
            raise ValueError("Agent returned an empty response.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat agent failed: {e}")

    return {"reply": final_text}
