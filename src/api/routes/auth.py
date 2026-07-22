"""Login + identity endpoints.

Passwords are bcrypt-hashed and loaded from Secret Manager (cloud) or
data/credentials.json (local) via `src.core.auth_store` — this route no longer
reads the file directly or compares plaintext.

Scope note (unchanged, still true): this is demo-grade identity to drive the
login page, role-aware sidebar, and manager gates. It is NOT a full server-side
auth guard — routes still trust a client-supplied user_id/role. For a real
deployment the intended boundary is Google IAP/SSO in front of Cloud Run
(WAI_TRUST_IAP lets the app read IAP's verified identity); see RUNBOOK.md.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src.core import auth_store, settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# IAP puts the verified identity here after Google SSO. Format is
# "accounts.google.com:user@example.com" — we take the part after the last ':'.
_IAP_EMAIL_HEADER = "x-goog-authenticated-user-email"


class LoginRequest(BaseModel):
    user_id: str
    password: str


@router.post("/login")
async def api_login(req: LoginRequest):
    """Verify a user_id/password pair against the (bcrypt-hashed) credentials."""
    account = auth_store.get_account(req.user_id)
    if not account or not auth_store.verify_password(account, req.password):
        raise HTTPException(status_code=401, detail="Invalid user ID or password.")

    return {
        "user_id": req.user_id,
        "display_name": account.get("display_name", req.user_id),
        "role": account.get("job_level", "individual_contributor"),
        "manager_id": account.get("manager_id", ""),
    }


@router.get("/directory/{user_id}")
async def api_get_directory_entry(user_id: str):
    """Public identity lookup (no password) — lets a page resolve another
    user_id (e.g. a manager_id) to a display name without exposing credentials."""
    entry = auth_store.public_entry(user_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Unknown user_id.")
    return entry


@router.get("/iap")
async def api_iap_identity(request: Request):
    """Report the IAP-verified identity, when the app runs behind Google IAP.

    Enabled only when WAI_TRUST_IAP=true (otherwise the header is spoofable and
    is ignored). The frontend can call this to seed a session from company SSO
    instead of the demo login form. Returns {authenticated: false} when off or
    when no IAP header is present.
    """
    if not settings.trust_iap():
        return {"authenticated": False, "reason": "iap_trust_disabled"}
    raw = request.headers.get(_IAP_EMAIL_HEADER, "")
    email = raw.split(":")[-1].strip() if raw else ""
    if not email:
        return {"authenticated": False, "reason": "no_iap_header"}
    return {"authenticated": True, "email": email}
