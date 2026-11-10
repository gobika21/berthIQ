"""Claude timeouts/outages fall back to rule-based advice, and every advisory reports its cost."""

import re
from types import SimpleNamespace

import anthropic
import httpx
import pytest

import app.agents.decision_support as decision
import app.claude_client as claude_client
from app.advisory_service import run_advisory
from app.agents.monitoring import SnapshotValidationError
from app.scenarios import SCENARIOS
from tests.conftest import GOOD_RECOMMENDATIONS


def _timeout(*args, **kwargs):
    raise anthropic.APITimeoutError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))


def test_timeout_falls_back_to_rule_based_advice(monkeypatch):
    monkeypatch.setattr(decision, "ask_claude", _timeout)
    result = run_advisory(SCENARIOS["critical"])

    assert result["ai_status"] == "fallback" and result["ai_error"] == "APITimeoutError"
    assert result["tier"] == "Critical"                      # rules don't need Claude
    assert result["evidence"]["metrics"] and result["impact"]
    assert [r["persona"] for r in result["recommendations"]] == list(decision.PERSONAS)
    queue = str(SCENARIOS["critical"]["vessel_queue_length"])
    for persona, message in result["advisories"].items():
        assert queue in message, persona                     # still cites the data
        assert len(re.findall(r"[.!?](?=\s|$)", message)) <= 4
        assert "AI-written advice was unavailable" in message


def test_unusable_reply_after_retry_falls_back(fake_claude):
    fake_claude["replies"] = ["not json", "still not json"]
    result = run_advisory(SCENARIOS["high"])
    assert result["ai_status"] == "fallback" and result["ai_error"] == "ValueError"
    assert len(fake_claude["decision"]) == 2                 # our own retry happened first


def test_low_tier_fallback_is_calm(monkeypatch):
    monkeypatch.setattr(decision, "ask_claude", _timeout)
    result = run_advisory(SCENARIOS["low"])
    assert "Keep the current schedule" in result["recommendations"][0]["action"]


def test_arabic_fallback_stays_arabic(monkeypatch):
    monkeypatch.setattr(decision, "ask_claude", _timeout)
    result = run_advisory({**SCENARIOS["high"], "language": "ar"})
    text = " ".join(result["advisories"].values())
    letters = [c for c in text if c.isalpha()]
    assert sum("؀" <= c <= "ۿ" for c in letters) / len(letters) > 0.8


def test_bad_input_is_still_rejected_not_hidden_by_fallback(monkeypatch):
    monkeypatch.setattr(decision, "ask_claude", _timeout)
    with pytest.raises(SnapshotValidationError):
        run_advisory({**SCENARIOS["high"], "berth_occupancy_rate": 85})


def test_success_reports_ok_status(fake_claude):
    result = run_advisory(SCENARIOS["medium"])
    assert result["ai_status"] == "ok" and result["ai_error"] is None


# ---------------------------------------------------------------- usage and cost
class _FakeMessages:
    def create(self, model, max_tokens, system, messages):
        text = GOOD_RECOMMENDATIONS if max_tokens == 1024 else "Short advisory."
        return SimpleNamespace(
            content=[SimpleNamespace(text=text)],
            usage=SimpleNamespace(input_tokens=100, output_tokens=20),
        )


def test_usage_counts_every_call_including_parallel_drafts(monkeypatch):
    monkeypatch.setattr(claude_client, "get_client", lambda: SimpleNamespace(messages=_FakeMessages()))
    result = run_advisory(SCENARIOS["critical"])

    usage = result["usage"]
    assert usage["claude_calls"] == 4                        # 1 decision + 3 drafts in threads
    assert usage["input_tokens"] == 400 and usage["output_tokens"] == 80
    expected = (400 * claude_client.PRICE_INPUT_PER_MTOK + 80 * claude_client.PRICE_OUTPUT_PER_MTOK) / 1e6
    assert usage["cost_usd"] == pytest.approx(expected)
    assert usage["latency_s"] >= 0


def test_client_has_short_timeout_and_bounded_retries(monkeypatch):
    monkeypatch.setattr(claude_client, "_client", None)
    client = claude_client.get_client()
    assert client.timeout == claude_client.TIMEOUT_S == 30
    assert client.max_retries == claude_client.MAX_RETRIES == 2
