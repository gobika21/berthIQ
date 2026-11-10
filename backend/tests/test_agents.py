import json

import pytest

from app.agents.classification import classify_snapshot
from app.agents.decision_support import PERSONAS, _parse_recommendations
from app.agents.monitoring import SnapshotValidationError, monitoring_node
from app.graph import run_pipeline
from app.scenarios import SCENARIOS
from tests.conftest import GOOD_RECOMMENDATIONS


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("scenario, tier", [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")])
def test_scenarios_classify_to_expected_tier(scenario, tier):
    assert classify_snapshot(SCENARIOS[scenario])["tier"] == tier


def test_overall_tier_is_worst_metric_and_names_driver():
    result = classify_snapshot({"port_name": "X", "berth_occupancy_rate": 0.2, "vessel_queue_length": 20,
                                "avg_waiting_time_hours": 1})
    assert result["tier"] == "Critical"
    assert result["driving_metrics"] == ["vessel_queue_length"]
    assert result["metric_tiers"]["berth_occupancy_rate"] == "Low"


def test_arabic_reasoning():
    result = classify_snapshot(SCENARIOS["high"], language="ar")
    assert "الميناء" in result["tier_reasoning"]


# ---------------------------------------------------------------- monitoring agent validation
BASE = {"port_name": "Rotterdam", "berth_occupancy_rate": 0.6, "vessel_queue_length": 5, "avg_waiting_time_hours": 8}


@pytest.mark.parametrize("override", [
    {"berth_occupancy_rate": 85},
    {"berth_occupancy_rate": -0.1},
    {"vessel_queue_length": -1},
    {"vessel_queue_length": 2.5},
    {"avg_waiting_time_hours": -3},
    {"port_name": "   "},
    {"language": "fr"},
    {"berth_occupancy_rate": True},
    {"situation": "x" * 501},
])
def test_monitoring_rejects_bad_snapshots(override):
    with pytest.raises(SnapshotValidationError):
        monitoring_node({"snapshot": {**BASE, **override}})


def test_monitoring_rejects_missing_fields():
    with pytest.raises(SnapshotValidationError):
        monitoring_node({"snapshot": {"port_name": "X"}})


def test_monitoring_normalises_queue_to_int():
    out = monitoring_node({"snapshot": {**BASE, "vessel_queue_length": 5.0}})
    assert out["snapshot"]["vessel_queue_length"] == 5 and isinstance(out["snapshot"]["vessel_queue_length"], int)


# ---------------------------------------------------------------- decision-support parsing
def test_parse_orders_personas_consistently():
    assert [r["persona"] for r in _parse_recommendations(GOOD_RECOMMENDATIONS)] == list(PERSONAS)


@pytest.mark.parametrize("wrapper", ["```json\n{}\n```", "Here you go:\n{}\nThanks!", "{}"])
def test_parse_tolerates_fences_and_prose(wrapper):
    assert len(_parse_recommendations(wrapper.format(GOOD_RECOMMENDATIONS))) == 3


@pytest.mark.parametrize("bad", [
    "not json",
    "{}",
    json.dumps([{"persona": "pirate", "action": "a", "reasoning": "b"}]),
    json.dumps([{"persona": "carrier", "action": "", "reasoning": "b"}]),
    json.dumps([{"persona": "carrier", "action": "a", "reasoning": "b"}]),  # missing two personas
])
def test_parse_rejects_invalid(bad):
    with pytest.raises(ValueError):
        _parse_recommendations(bad)


# ---------------------------------------------------------------- full pipeline (Claude mocked)
def test_pipeline_runs_end_to_end(fake_claude):
    result = run_pipeline(SCENARIOS["critical"])
    assert result["tier"] == "Critical"
    assert len(result["recommendations"]) == 3
    assert set(result["advisories"]) == set(PERSONAS)
    assert fake_claude["drafting"] == 3
    assert result["precedents"], "retrieval should find at least one precedent"


def test_pipeline_retries_once_on_bad_json(fake_claude):
    fake_claude["replies"] = ["definitely not json", GOOD_RECOMMENDATIONS]
    run_pipeline(SCENARIOS["high"])
    assert len(fake_claude["decision"]) == 2
    assert "previous reply was invalid" in fake_claude["decision"][1]


def test_pipeline_gives_up_after_second_bad_reply(fake_claude):
    fake_claude["replies"] = ["[]", "[]"]
    with pytest.raises(ValueError):
        run_pipeline(SCENARIOS["low"])


def test_situation_reaches_decision_prompt(fake_claude):
    run_pipeline({**SCENARIOS["high"], "situation": "Gale expected at 18:00"})
    assert "Gale expected at 18:00" in fake_claude["decision"][0]


# ---------------------------------------------------------------- live-only tiering
def test_tier_metrics_excludes_rough_estimate():
    snap = {"port_name": "X", "berth_occupancy_rate": 1.0, "vessel_queue_length": 1, "avg_waiting_time_hours": 1,
            "tier_metrics": ["vessel_queue_length", "avg_waiting_time_hours"]}
    result = classify_snapshot(snap)
    assert result["tier"] == "Low"                       # a saturated estimate can't make it Critical
    assert "berth_occupancy_rate" not in result["metric_tiers"]


@pytest.mark.parametrize("bad", [[], ["port_name"], ["nonsense"], "vessel_queue_length"])
def test_monitoring_rejects_bad_tier_metrics(bad):
    with pytest.raises(SnapshotValidationError):
        monitoring_node({"snapshot": {**BASE, "tier_metrics": bad}})


def test_decision_prompt_flags_unused_estimate(fake_claude):
    run_pipeline({**SCENARIOS["low"], "berth_occupancy_rate": 1.0,
                  "tier_metrics": ["vessel_queue_length", "avg_waiting_time_hours"]})
    prompt = fake_claude["decision"][0]
    assert "Congestion level: Low" in prompt and "not reliably measured" in prompt
    assert "100%" not in prompt  # the unreliable number is never shown to the model


# ---------------------------------------------------------------- port-relative queue tiers
from app.thresholds import effective_thresholds

LIVE = ["vessel_queue_length", "avg_waiting_time_hours"]


@pytest.mark.parametrize("queue, tier", [(23, "Low"), (30, "Medium"), (33, "High"), (45, "Critical")])
def test_queue_judged_against_port_baseline(queue, tier):
    snap = {"port_name": "Singapore", "berth_occupancy_rate": 0.5, "vessel_queue_length": queue,
            "avg_waiting_time_hours": 1, "tier_metrics": LIVE, "queue_baseline": 22}
    assert classify_snapshot(snap)["tier"] == tier


def test_without_baseline_global_thresholds_apply():
    snap = {"port_name": "X", "berth_occupancy_rate": 0.5, "vessel_queue_length": 23,
            "avg_waiting_time_hours": 1, "tier_metrics": LIVE}
    assert classify_snapshot(snap)["tier"] == "Critical"


def test_tiny_baseline_is_floored():
    # usual queue of 1 → floored to 3, so 4 ships is Medium (1.33×), not "4× normal"
    assert effective_thresholds("vessel_queue_length", 1) == {"Low": 3.6, "Medium": 4.5, "High": 6.0}
    snap = {"port_name": "X", "berth_occupancy_rate": 0.5, "vessel_queue_length": 4,
            "avg_waiting_time_hours": 1, "tier_metrics": LIVE, "queue_baseline": 1}
    assert classify_snapshot(snap)["tier"] == "Medium"


def test_reasoning_and_prompt_mention_usual_level(fake_claude):
    snap = {"port_name": "Singapore", "berth_occupancy_rate": 0.5, "vessel_queue_length": 45,
            "avg_waiting_time_hours": 1, "tier_metrics": LIVE, "queue_baseline": 22}
    assert "usual for this port: about 22" in classify_snapshot(snap)["tier_reasoning"]
    run_pipeline(snap)
    assert "usual level is about 22" in fake_claude["decision"][0]


@pytest.mark.parametrize("bad", [-1, "22", True, float("nan")])
def test_monitoring_rejects_bad_baseline(bad):
    with pytest.raises(SnapshotValidationError):
        monitoring_node({"snapshot": {**BASE, "queue_baseline": bad}})
