import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def post(body):
    return client.post("/agent/run", json=body)


def test_contract_fields_and_enums():
    r = post({"conversation_id": "cv_x", "today": "2026-10-01", "turns": ["Dr. Rao Saturday 3 tareekh subah appointment", "Harpreet Singh 9812200311"]})
    body = r.json()
    assert r.status_code == 200 and body["conversation_id"] == "cv_x" and body["terminal_state"] == "booked"
    assert body["escalation_reason"] is None and set(body["metrics"]) >= {"turns", "tokens", "latency_ms"}
    assert all(set(c) == {"name", "arguments"} for c in body["tool_calls"])


@pytest.mark.parametrize("body,field", [
    ({"today": "2026-10-01", "turns": []}, "conversation_id"),
    ({"conversation_id": "a", "today": "01-10-2026", "turns": []}, "today"),
    ({"conversation_id": "a", "today": "2026-02-30", "turns": []}, "today"),
    ({"conversation_id": "a", "today": "2026-10-01", "turns": "hello"}, "turns"),
    ({"conversation_id": "a", "today": "2026-10-01", "turns": [1, 2]}, "turns"),
])
def test_bad_requests_get_422_with_the_field_named_not_500(body, field):
    r = post(body)
    assert r.status_code == 422 and r.json()["detail"]["field"] == field


def test_non_json_body_is_422():
    assert client.post("/agent/run", content=b"not json", headers={"content-type": "application/json"}).status_code == 422


def test_empty_turns_do_not_crash():
    assert post({"conversation_id": "a", "today": "2026-10-01", "turns": []}).json()["terminal_state"] == "abandoned"


def test_tool_endpoint_returns_actionable_422():
    r = client.post("/tools/search_slots", json={"doctor_id": "dr_rao", "date": "tomorrow"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_DATE"
    assert client.post("/tools/nope", json={}).status_code == 404


def test_handoff_queue_flow():
    client.post("/api/demo/seed")
    s = client.get("/api/summary").json()
    assert s["escalated"] >= 1 and s["urgent_open"] >= 1
    handoffs = client.get("/api/handoffs").json()
    target = next(h for h in handoffs if h["reason"] == "clinical_urgent" and h["status"] == "open")
    assert client.post(f"/api/handoffs/{target['conversation_id']}/resolve").status_code == 200
    assert client.post(f"/api/handoffs/{target['conversation_id']}/resolve").status_code == 404
    detail = client.get(f"/api/conversations/{target['conversation_id']}").json()
    assert any(e["kind"] == "tool" for e in detail["events"]) and "stability" in detail
