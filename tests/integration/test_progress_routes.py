"""Regression test for the manager-dashboard status bug found during UAT:
course_started previously only set current_course_id, never current_state,
so a learner who had started (but not finished) a course still showed
"Not Started" on the manager dashboard indefinitely.
"""


def test_course_started_advances_status_to_in_progress(client, test_data_dir, seed_progress):
    seed_progress(test_data_dir, "operations", "emp_x", manager_id="manager", current_state="enrolled")

    resp = client.post(
        "/api/user/emp_x/progress?department=operations",
        json={"event_type": "course_started", "event_data": {"course_id": "course_1"}},
    )
    assert resp.status_code == 200
    assert resp.json()["current_state"] == "course_in_progress"

    report = client.get("/api/manager/manager/reports?department=operations&role=manager").json()
    row = next(r for r in report["reports"] if r["user_id"] == "emp_x")
    assert row["status"] == "In Progress"
    assert row["current_course_id"] == "course_1"


def test_course_started_does_not_downgrade_completed_state(client, test_data_dir, seed_progress):
    seed_progress(test_data_dir, "operations", "emp_y", manager_id="manager", current_state="completed")

    resp = client.post(
        "/api/user/emp_y/progress?department=operations",
        json={"event_type": "course_started", "event_data": {"course_id": "course_2"}},
    )
    assert resp.status_code == 200
    assert resp.json()["current_state"] == "completed"
