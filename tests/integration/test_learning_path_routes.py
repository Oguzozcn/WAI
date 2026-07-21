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


def test_learning_path_by_id_merges_remedial(client, test_data_dir, seed_progress):
    """Regression test for the UAT audit finding: /api/learning-path/{path_id}
    (what dashboard.html and learning-path.html actually render) must show a
    learner's pending remedial courses, not just /api/learning-path/latest."""
    _seed_standard_path("operations", "path_ops_202", ["course_a", "course_b"])
    client.post(
        "/api/learning-path/path_ops_202/enroll",
        params={"user_id": "emp_004", "department": "operations"},
    )
    seed_progress(
        test_data_dir, "operations", "emp_004",
        remedial_courses=[{
            "course_id": "remedial_xyz",
            "source_course_id": "course_a",
            "title": "Targeted Review",
        }],
    )

    resp = client.get(
        "/api/learning-path/path_ops_202",
        params={"user_id": "emp_004", "department": "operations"},
    )
    assert resp.status_code == 200
    course_ids = [c["course_id"] for c in resp.json()["courses"]]
    assert "remedial_xyz" in course_ids
    # placed right after the source course it targets
    assert course_ids.index("remedial_xyz") == course_ids.index("course_a") + 1


def test_learning_path_by_id_without_user_id_unchanged(client, test_data_dir):
    """No user_id → no merge attempted, path returned as-stored (existing callers
    that don't pass user_id must see identical behavior to before this change)."""
    _seed_standard_path("operations", "path_ops_203", ["course_a"])
    client.post(
        "/api/learning-path/path_ops_203/enroll",
        params={"user_id": "emp_005", "department": "operations"},
    )

    resp = client.get("/api/learning-path/path_ops_203", params={"department": "operations"})
    assert resp.status_code == 200
    assert [c["course_id"] for c in resp.json()["courses"]] == ["course_a"]
