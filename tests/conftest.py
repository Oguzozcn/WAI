"""Shared pytest fixtures for the WisdomAI_MVP test suite.

Critical isolation contract
---------------------------
Every fixture that touches storage points the app at an isolated temp
directory via the ``WAI_DATA_DIR`` env var (see ``DepartmentScopedStore`` /
``KPIStoreReader`` in ``src/core/database.py``). No test may read or write the
real ``data/`` directory.
"""

import json
import sys
from pathlib import Path

import pytest

# Ensure the project root is importable (mirrors src/api/main.py).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def test_data_dir(tmp_path, monkeypatch):
    """Redirect all DepartmentScopedStore/KPIStoreReader I/O into a temp dir.

    Yields the temp Path so tests can inspect/seed files directly.
    """
    monkeypatch.setenv("WAI_DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture
def client(test_data_dir):
    """A FastAPI TestClient whose route handlers use the isolated data dir.

    ``src.api.main`` is imported INSIDE the fixture body (after
    ``test_data_dir`` has set ``WAI_DATA_DIR``) so that any store constructed
    during a request resolves to the temp directory, never the real ``data/``.
    """
    from fastapi.testclient import TestClient
    from src.api.main import app

    return TestClient(app)


@pytest.fixture
def mock_gemini(monkeypatch):
    """Monkeypatch ``get_gemini_client`` everywhere it was imported directly.

    Both ``quiz_service`` and ``curriculum_service`` do
    ``from src.services.llm_client import get_gemini_client`` so we patch the
    name bound in each module.

    Returns a callable ``patch(response_text="{}")`` that installs a fake client.
    Pass a string to have ``generate_content`` return that text, or pass an
    ``Exception`` instance to have it raise (to exercise fallback paths).
    """

    class _FakeResponse:
        def __init__(self, text):
            self.text = text

    class _FakeModels:
        def __init__(self, response_text):
            self._response_text = response_text

        def generate_content(self, model, contents):
            if isinstance(self._response_text, Exception):
                raise self._response_text
            return _FakeResponse(self._response_text)

    class _FakeClient:
        def __init__(self, response_text):
            self.models = _FakeModels(response_text)

    def _make_patcher(response_text="{}"):
        fake_client = _FakeClient(response_text)
        fake_factory = lambda: fake_client
        monkeypatch.setattr(
            "src.services.quiz_service.get_gemini_client", fake_factory
        )
        monkeypatch.setattr(
            "src.services.curriculum_service.get_gemini_client", fake_factory
        )
        return fake_client

    return _make_patcher


@pytest.fixture
def seed_progress():
    """Fixture wrapper exposing ``seed_user_progress`` to tests as a callable."""
    return seed_user_progress


def seed_user_progress(data_dir, department, user_id, **overrides):
    """Write a minimal UserProgress-shaped JSON directly into WAI_DATA_DIR.

    Field names match ``src.core.models.UserProgress`` and the directory layout
    (``user_progress/<department>/<user_id>.json``) expected by
    ``DepartmentScopedStore.read_user_progress`` / ``read_all_user_progress``.
    """
    base = {
        "user_id": user_id,
        "department": department,
        "display_name": user_id,
        "current_state": "enrolled",
        "completed_courses": [],
        "quiz_attempts": [],
        "readiness_score": 0.0,
        "error_retention_matrix": {},
        "manager_id": "",
        "job_level": "individual_contributor",
    }
    base.update(overrides)
    progress_dir = Path(data_dir) / "user_progress" / department
    progress_dir.mkdir(parents=True, exist_ok=True)
    (progress_dir / f"{user_id}.json").write_text(json.dumps(base, indent=2))
    return base
