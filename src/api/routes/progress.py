from fastapi import APIRouter
from pydantic import BaseModel
from src.services.user_service import get_user_progress, update_progress
from WAI_agent.shared.constants import DEFAULT_DEPARTMENT

router = APIRouter(prefix="/api/user", tags=["progress"])

class ProgressUpdateRequest(BaseModel):
    event_type: str
    event_data: dict = {}

@router.get("/{user_id}/progress")
async def api_get_progress(user_id: str, department: str = DEFAULT_DEPARTMENT):
    """Get user progress data for the dashboard."""
    result = get_user_progress(user_id=user_id, department=department)
    return result

@router.post("/{user_id}/progress")
async def api_update_progress(user_id: str, body: ProgressUpdateRequest, department: str = DEFAULT_DEPARTMENT):
    """Update user progress with a new event."""
    result = update_progress(
        user_id=user_id,
        event_type=body.event_type,
        event_data=body.event_data,
        department=department,
    )
    return result
