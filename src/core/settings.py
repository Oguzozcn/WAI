"""Central environment-driven settings.

One place that reads the deployment knobs documented in `.env.example`. Values
are read at call time (not import time) so tests can monkeypatch the environment
and so a process that changes STORAGE mid-run behaves predictably. Nothing here
has side effects — importing this module touches no cloud service.
"""

import os


def storage_backend() -> str:
    """'local' (filesystem under data/, the default) or 'cloud' (Firestore + GCS)."""
    return os.getenv("STORAGE", "local").strip().lower()


def is_cloud_storage() -> bool:
    return storage_backend() == "cloud"


def gcs_bucket() -> str:
    """Bucket name for binary blobs in cloud mode (required when STORAGE=cloud)."""
    return os.getenv("WAI_GCS_BUCKET", "").strip()


def firestore_database() -> str:
    """Firestore database id; '(default)' unless a named database was created."""
    return os.getenv("WAI_FIRESTORE_DATABASE", "(default)").strip() or "(default)"


def firestore_prefix() -> str:
    """Collection-name prefix that namespaces this app's Firestore data."""
    return os.getenv("WAI_FIRESTORE_PREFIX", "wai").strip() or "wai"


def gcp_project() -> str:
    return os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()


def credentials_json_env() -> str:
    """Raw credentials.json content injected via Secret Manager (cloud). Wins over the file."""
    return os.getenv("WAI_CREDENTIALS_JSON", "").strip()


def credentials_path() -> str:
    """Filesystem path to credentials.json for local dev (overridable)."""
    return os.getenv("WAI_CREDENTIALS_PATH", "").strip()


def trust_iap() -> bool:
    """Trust Google IAP's signed identity header. Only enable when actually behind IAP."""
    return os.getenv("WAI_TRUST_IAP", "false").strip().lower() in ("1", "true", "yes")
