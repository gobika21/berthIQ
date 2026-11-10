import os
import sys
import tempfile

# Must be set before the app is imported: no background AIS/monitor tasks, and
# history/alert files go to a throwaway directory instead of app/live/.
os.environ["BERTHIQ_DISABLE_BACKGROUND"] = "1"
os.environ["BERTHIQ_DATA_DIR"] = tempfile.mkdtemp(prefix="berthiq-test-")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import pytest

GOOD_RECOMMENDATIONS = json.dumps([
    {"persona": "terminal_operator", "action": "Open extra shifts", "reasoning": "The port is 95% full."},
    {"persona": "carrier", "action": "Slow down inbound ships", "reasoning": "22 ships are waiting."},
    {"persona": "trucking_company", "action": "Pre-book pickup slots", "reasoning": "Waits average 30 hours."},
])


@pytest.fixture
def fake_claude(monkeypatch):
    """Replace every Claude call with canned replies; returns the list of prompts seen."""
    import app.agents.advisory_drafting as drafting
    import app.agents.decision_support as decision

    calls = {"decision": [], "drafting": 0, "replies": [GOOD_RECOMMENDATIONS]}

    def decide(system, user, max_tokens=1024):
        calls["decision"].append(user)
        return calls["replies"].pop(0) if calls["replies"] else GOOD_RECOMMENDATIONS

    def draft(system, user, max_tokens=300):
        calls["drafting"] += 1
        return f"Advisory for {user.splitlines()[1]}"

    monkeypatch.setattr(decision, "ask_claude", decide)
    monkeypatch.setattr(drafting, "ask_claude", draft)
    return calls
