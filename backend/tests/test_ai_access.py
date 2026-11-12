"""Who pays for Claude: a visitor's own key, the server's free daily quota, or nobody."""

import logging

import pytest
from fastapi.testclient import TestClient

import app.agents.decision_support as decision
import app.ai_quota as ai_quota
import app.claude_client as claude_client
import app.main as main
from app.monitoring.monitor import monitor
from app.scenarios import SCENARIOS

VISITOR_KEY = "sk-ant-api03-" + "v" * 40


@pytest.fixture
def client(fake_claude, monkeypatch):
    """Like the API client, but each decision call first goes through get_client(), so the
    per-request access is really applied; records which access each call ran with."""
    seen = []
    fake_decide = decision.ask_claude

    def decide(system, user, max_tokens=1024):
        claude_client.get_client()  # raises NoClaudeAccess when this request has no Claude
        access = claude_client._access.get()
        seen.append(access[0] if access else "default")
        return fake_decide(system, user, max_tokens)

    monkeypatch.setattr(decision, "ask_claude", decide)
    monkeypatch.setattr(ai_quota, "FREE_AI_RUNS_PER_DAY", 2)
    ai_quota.reset_for_tests()
    main._llm_calls.clear()
    with TestClient(main.app) as c:
        c.seen = seen
        yield c


def test_free_runs_then_rule_based_advice(client):
    bodies = [client.post("/advisory", json=SCENARIOS["high"]).json() for _ in range(3)]
    assert [b["ai_status"] for b in bodies] == ["ok", "ok", "fallback"]
    assert bodies[2]["ai_error"] == "free_quota_used"
    assert len(bodies[2]["recommendations"]) == 3  # still useful advice, and the tier is unaffected
    assert bodies[2]["tier"] == bodies[0]["tier"]
    assert client.seen == ["server", "server"]
    assert client.get("/ai/quota").json() == {"free_runs_per_day": 2, "free_runs_left": 0}


def test_visitor_key_is_used_and_does_not_spend_the_quota(client):
    res = client.post("/advisory", json=SCENARIOS["high"], headers={"X-Anthropic-Key": VISITOR_KEY})
    assert res.status_code == 200 and res.json()["ai_status"] == "ok"
    assert client.seen == ["own"]
    assert client.get("/ai/quota").json()["free_runs_left"] == 2


def test_visitor_key_still_works_after_the_quota_is_used(client):
    for _ in range(2):
        client.post("/advisory", json=SCENARIOS["low"])
    res = client.post("/advisory", json=SCENARIOS["low"], headers={"X-Anthropic-Key": VISITOR_KEY})
    assert res.json()["ai_status"] == "ok"


def test_malformed_key_is_rejected(client):
    res = client.post("/advisory", json=SCENARIOS["low"], headers={"X-Anthropic-Key": "hello"})
    assert res.status_code == 400
    assert "sk-ant-" in res.json()["detail"]


def test_no_server_key_means_visitor_key_or_rule_based(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    body = client.post("/advisory", json=SCENARIOS["low"]).json()
    assert body["ai_status"] == "fallback" and body["ai_error"] == "no_key"
    assert client.get("/ai/quota").json() == {"free_runs_per_day": 0, "free_runs_left": 0}


def test_visitor_key_never_appears_in_logs_or_responses(client, caplog):
    caplog.set_level(logging.DEBUG)
    res = client.post("/advisory", json=SCENARIOS["high"], headers={"X-Anthropic-Key": VISITOR_KEY})
    assert VISITOR_KEY not in res.text
    assert VISITOR_KEY not in caplog.text


def test_cors_allows_the_key_header():
    with TestClient(main.app) as c:
        res = c.options("/advisory", headers={
            "Origin": main.ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-anthropic-key",
        })
    assert res.status_code == 200
    assert "x-anthropic-key" in res.headers["access-control-allow-headers"].lower()


def test_monitor_does_not_draft_on_its_own_once_the_quota_is_used(monkeypatch):
    from app.agents.classification import classify_snapshot
    from app.monitoring.detectors import escalation_alert

    scheduled = []
    monkeypatch.setattr(monitor, "schedule_advisory", scheduled.append)
    monkeypatch.setattr(ai_quota, "FREE_AI_RUNS_PER_DAY", 1)
    ai_quota.reset_for_tests()
    monitor._advisory_times.clear()

    snap = {**SCENARIOS["high"], "port_name": "Testport"}
    cls = classify_snapshot(snap)
    for i in range(2):
        spec = escalation_alert(f"testport{i}", "Testport", "Medium", cls["tier"], cls, snap)
        monitor.raise_alert(f"testport{i}", "Testport", spec, snap, demo=True)
    assert len(scheduled) == 1  # the second alert waits for someone to request advice
    assert ai_quota.free_runs_left() == 0
