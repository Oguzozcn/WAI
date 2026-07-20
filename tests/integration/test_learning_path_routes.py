"""Integration tests for the /api/learning-path routes via FastAPI TestClient.

Focused on /enroll, the route Phase 1's seed-data fix depends on: it's how a
manager-visible employee actually gets attached to a path.
"""

from src.core.database import DepartmentScopedStore


def _seed_standard_path(department, path_id, course_ids):
    store = DepartmentScopedStore(department)
    store.write_standard_path(path_id, {
        "path_id": path_id,
        "title": "Operations Onboarding",
        "path_type": "official",
        "courses": [{"course_id": cid, "title": cid} for cid in course_ids],
    })
    return store


def test_enroll_official_path_appears_in_enrolled_list(client, test_data_dir):
    _seed_standard_path("operations", "path_ops_101", ["course_a", "course_b"])

    resp = client.post(
        "/api/learning-path/path_ops_101/enroll",
        params={"user_id": "emp_003", "department": "operations"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "enrolled", "path_id": "path_ops_101"}

    enrolled = client.get(
        "/api/learning-path/enrolled",
        params={"user_id": "emp_003", "department": "operations"},
    )
    assert enrolled.status_code == 200
    body = enrolled.json()
    assert body["count"] == 1
    assert body["enrolled_paths"][0]["path_id"] == "path_ops_101"
    assert body["enrolled_paths"][0]["total_courses"] == 2


def test_enroll_unknown_path_404(client):
    resp = client.post(
        "/api/learning-path/does_not_exist/enroll",
        params={"user_id": "emp_003", "department": "operations"},
    )
    assert resp.status_code == 404


def test_enroll_unofficial_path_without_user_id_400(client):
    resp = client.post(
        "/api/learning-path/some_draft/enroll",
        params={"path_type": "unofficial", "department": "operations"},
    )
    assert resp.status_code == 400
