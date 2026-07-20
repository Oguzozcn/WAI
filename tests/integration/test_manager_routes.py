"""Integration tests for the /api/manager routes and lazy KPI generation."""

from unittest.mock import Mock

from src.services import reporting_service


def _seed_team(seed_progress, data_dir):
    """Seed 3 direct reports of manager 'manager' with varied metrics.

    readiness scores: 0.9, 0.6, 0.3 → average 0.6
    """
    seed_progress(
        data_dir, "operations", "u_high",
        manager_id="manager", readiness_score=0.9,
        completed_courses=["c1", "c2", "c3"], current_state="passed",
    )
    seed_progress(
        data_dir, "operations", "u_mid",
        manager_id="manager", readiness_score=0.6,
        completed_courses=["c1"], current_state="course_in_progress",
    )
    seed_progress(
        data_dir, "operations", "u_low",
        manager_id="manager", readiness_score=0.3,
        completed_courses=[], current_state="enrolled",
    )


def test_team_kpis_aggregates(client, test_data_dir, seed_progress):
    _seed_team(seed_progress, test_data_dir)

    resp = client.get("/api/manager/manager/team-kpis?department=operations&role=manager")
    assert resp.status_code == 200
    body = resp.json()

    assert body["team_size"] == 3
    # (0.9 + 0.6 + 0.3) / 3 = 0.6
    assert body["avg_readiness_score"] == 0.6


def test_reports_sorted_by_readiness_ascending(client, test_data_dir, seed_progress):
    _seed_team(seed_progress, test_data_dir)

    resp = client.get("/api/manager/manager/reports?department=operations&role=manager")
    assert resp.status_code == 200
    rows = resp.json()["reports"]

    assert len(rows) == 3
    scores = [r["readiness_score"] for r in rows]
    assert scores == sorted(scores)
    assert scores == [0.3, 0.6, 0.9]


def test_team_kpis_unknown_manager_404(client, test_data_dir):
    resp = client.get("/api/manager/nonexistent_manager/team-kpis?department=operations&role=manager")
    assert resp.status_code == 404


def test_ensure_kpi_payload_generates_once_per_day(test_data_dir, seed_progress, monkeypatch):
    seed_progress(test_data_dir, "operations", "u1", readiness_score=0.7)
    seed_progress(test_data_dir, "operations", "u2", readiness_score=0.5)

    # First call synthesizes and persists today's payload.
    payload = reporting_service.ensure_kpi_payload_for_today("operations")
    assert payload is not None

    kpi_files = list((test_data_dir / "kpi_store").glob("*.json"))
    assert len(kpi_files) == 1

    # Second call must NOT re-synthesize — today's payload already exists.
    spy = Mock(wraps=reporting_service.synthesize_department_kpi)
    monkeypatch.setattr(reporting_service, "synthesize_department_kpi", spy)

    payload2 = reporting_service.ensure_kpi_payload_for_today("operations")
    assert payload2 is not None
    assert spy.call_count == 0
