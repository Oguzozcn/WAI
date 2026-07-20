"""Integration tests for the /api/auth/login route via FastAPI TestClient.

auth.py deliberately reads the real data/credentials.json (see its module
docstring) rather than an isolated WAI_DATA_DIR-scoped store, so these tests
exercise the real checked-in file. They exist to guard the Phase 1 seed-data
fix: emp_003/004/005 gained credentials entries so they can log in and appear
on the manager dashboard, and a login test protects that from regressing.
"""

import pytest


@pytest.mark.parametrize(
    "user_id,password,expected_role,expected_manager",
    [
        ("emp_003", "james123", "individual_contributor", "manager"),
        ("emp_004", "priya123", "individual_contributor", "manager"),
        ("emp_005", "david123", "individual_contributor", "manager"),
    ],
)
def test_login_succeeds_for_seeded_employees(client, user_id, password, expected_role, expected_manager):
    resp = client.post("/api/auth/login", json={"user_id": user_id, "password": password})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["role"] == expected_role
    assert body["manager_id"] == expected_manager


def test_login_wrong_password_401(client):
    resp = client.post("/api/auth/login", json={"user_id": "emp_003", "password": "wrong"})
    assert resp.status_code == 401


def test_login_unknown_user_401(client):
    resp = client.post("/api/auth/login", json={"user_id": "nobody", "password": "whatever"})
    assert resp.status_code == 401
