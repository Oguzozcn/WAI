from fastapi import APIRouter
from src.services.user_service import get_department_readiness, flag_at_risk_users
from src.core.config import DEFAULT_DEPARTMENT

router = APIRouter(prefix="/api/department", tags=["department"])

@router.get("/readiness")
async def api_department_readiness(department: str = DEFAULT_DEPARTMENT):
    """Get department-level readiness metrics."""
    result = get_department_readiness(department=department)
    return result

@router.get("/at-risk")
async def api_at_risk(department: str = DEFAULT_DEPARTMENT):
    """Get at-risk users for a department."""
    result = flag_at_risk_users(department=department)
    return result
