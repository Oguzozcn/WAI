"""Credential loading + password verification.

Where the accounts come from (first hit wins):
  1. WAI_CREDENTIALS_JSON env var — the whole credentials.json content, injected
     from Secret Manager on Cloud Run (so no secret ships in the image or git).
  2. WAI_CREDENTIALS_PATH file, if set.
  3. data/credentials.json at the project root (local dev / fresh clone default).

Passwords are stored bcrypt-hashed under `password_hash`. A legacy plaintext
`password` field is still accepted so an un-migrated file keeps working — but the
checked-in file carries hashes only. These are throwaway *demo* accounts; real
company access is intended to sit behind Google IAP/SSO at the edge (see RUNBOOK).
"""

import json
import os
from pathlib import Path
from typing import Optional

import bcrypt

from src.core import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CREDENTIALS_PATH = _PROJECT_ROOT / "data" / "credentials.json"


def _resolve_path() -> Path:
    override = settings.credentials_path()
    return Path(override) if override else _DEFAULT_CREDENTIALS_PATH


def load_credentials() -> dict:
    """Return the full accounts dict (may include password/password_hash fields)."""
    env_blob = settings.credentials_json_env()
    if env_blob:
        try:
            return json.loads(env_blob)
        except json.JSONDecodeError:
            return {}
    path = _resolve_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def get_account(user_id: str) -> Optional[dict]:
    return load_credentials().get(user_id)


def hash_password(plaintext: str) -> str:
    """bcrypt-hash a plaintext password (used by the migration/seed script)."""
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(account: dict, password: str) -> bool:
    """True if `password` matches the account's stored hash (or legacy plaintext)."""
    if not account:
        return False
    stored_hash = account.get("password_hash")
    if stored_hash:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except (ValueError, TypeError):
            return False
    # Legacy fallback: un-migrated plaintext file.
    legacy = account.get("password")
    return legacy is not None and password == legacy


def public_entry(user_id: str) -> Optional[dict]:
    """Identity fields safe to expose (never password/password_hash)."""
    account = get_account(user_id)
    if not account:
        return None
    return {
        "user_id": user_id,
        "display_name": account.get("display_name", user_id),
        "role": account.get("job_level", "individual_contributor"),
    }
