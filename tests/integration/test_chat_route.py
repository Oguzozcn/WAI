"""Integration test for /api/chat — hits the real ADK agent + Gemini via ADC.

Marked ``llm`` so it is EXCLUDED from a default ``pytest`` run. Opt in with
``pytest -m llm`` (requires Google ADC and costs real API calls).
"""

import pytest


@pytest.mark.llm
def test_chat_returns_reply(client, test_data_dir, seed_progress):
    seed_progress(test_data_dir, "operations", "chat_user", readiness_score=0.5)

    resp = client.post(
        "/api/chat",
        json={
            "user_id": "chat_user",
            "department": "operations",
            "message": "Hello, what can you help me with?",
        },
    )
    assert resp.status_code == 200
    reply = resp.json()["reply"]
    assert isinstance(reply, str)
    assert reply.strip() != ""
