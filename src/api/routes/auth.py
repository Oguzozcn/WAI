"""Login endpoint for the single-department simulation.

Intentionally lightweight: this app has no other real security boundary
(every route already trusts a client-supplied user_id), so this adds just
enough identity to drive the login page, role-aware sidebar, and manager
gates the simulation needs — not a production auth system.
"""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth", tags=["auth"])

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "data" / "credentials.json"


def _read_credentials() -> dict:
    if not CREDENTIALS_PATH.exists():
        return {}
    return json.loads(CREDENTIALS_PATH.read_text())


class LoginRequest(BaseModel):
    user_id: str
    password: str


@router.post("/login")
async def api_login(req: LoginRequest):
    """Verify a user_id/password pair against data/credentials.json."""
    credentials = _read_credentials()
    account = credentials.get(req.user_id)
    if not account or account.get("password") != req.password:
        raise HTTPException(status_code=401, detail="Invalid user ID or password.")

    return {
        "user_id": req.user_id,
        "display_name": account.get("display_name", req.user_id),
        "role": account.get("job_level", "individual_contributor"),
        "manager_id": account.get("manager_id", ""),
    }
