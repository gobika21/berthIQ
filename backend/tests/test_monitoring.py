import pytest

from app.geo import haversine_m
from app.impact import MIN_SPEED_KN, SERVICE_SPEED_KN, estimate_impact
from app.monitoring.alerts import AlertError, AlertStore
from app.monitoring.detectors import AnchorDragTracker, TierTracker, anchor_drag_alerts, drag_candidates, weather_alert


# ---------------------------------------------------------------- tier escalation
def test_escalation_needs_consecutive_confirmations():
    tr = TierTracker(confirm_ticks=2)
    assert tr.update("p", "Low") is None
    assert tr.update("p", "Low") is None          # Low confirmed, no alert
    assert tr.update("p", "High") is None         # first sighting only
    assert tr.update("p", "High") == ("Low", "High")
    assert tr.update("p", "High") is None         # already confirmed


def test_single_noisy_reading_does_not_alert():
    tr = TierTracker(confirm_ticks=2)
    tr.update("p", "Low"), tr.update("p", "Low")
    assert tr.update("p", "Critical") is None
    assert tr.update("p", "Low") is None          # back to normal, candidate cleared
    assert tr.confirmed("p") == "Low"


def test_de_escalation_does_not_alert():
    tr = TierTracker(confirm_ticks=1)
    tr.update("p", "High")
    assert tr.update("p", "Low") is None
    assert tr.confirmed("p") == "Low"


def test_first_confirmation_alerts_only_when_already_bad():
    assert TierTracker(confirm_ticks=1).update("a", "Medium") == ("Low", "Medium")
    assert TierTracker(confirm_ticks=1).update("b", "Low") is None


# ---------------------------------------------------------------- anchor drag
def _anchored(drift_m):
    return {"mmsi": "123", "lat": 0, "lon": 0, "anchor_lat": 0, "anchor_lon": 0, "drift_m": drift_m, "speed_knots": 1.2}


def _ship(drift_m, speed_knots=1.0, mmsi="123"):
    return {"mmsi": mmsi, "lat": 0, "lon": 0, "anchor_lat": 0, "anchor_lon": 0,
            "drift_m": drift_m, "speed_knots": speed_knots}


def test_drag_candidates_ignore_swinging_and_stale_status_ships():
    # Real cases from the first live alerts: a big ship swinging 515 m on its chain, and
    # a ship doing 22.7 kn that never switched off its "at anchor" status.
    assert drag_candidates([_ship(515, 0.1)], threshold_m=800) == []
    assert drag_candidates([_ship(3223, 22.7)], threshold_m=800) == []
    assert drag_candidates([_ship(950, 1.2)], threshold_m=800) == [_ship(950, 1.2)]


def test_drag_needs_consecutive_growing_drift():
    t = AnchorDragTracker(confirm_ticks=2)
    assert t.update("p", [_ship(900)]) == []                     # first sighting
    assert [v["mmsi"] for v in t.update("p", [_ship(980)])] == ["123"]   # still moving away


def test_drag_not_confirmed_when_ship_swings_back_or_returns_inside_line():
    t = AnchorDragTracker(confirm_ticks=2)
    t.update("p", [_ship(900)])
    assert t.update("p", [_ship(850)]) == []                     # moved back: swinging, not dragging
    t.update("p", [])                                            # back inside the line: streak reset
    assert t.update("p", [_ship(1000)]) == []


def test_drag_streaks_are_per_ship_and_per_port():
    t = AnchorDragTracker(confirm_ticks=2)
    t.update("a", [_ship(900, mmsi="1")])
    t.update("b", [])                                            # another port's check doesn't reset "a"
    assert [v["mmsi"] for v in t.update("a", [_ship(950, mmsi="1"), _ship(900, mmsi="2")])] == ["1"]


def test_anchor_drag_threshold_and_severity():
    assert anchor_drag_alerts("p", "Port", [_anchored(200)], threshold_m=500) == []
    high = anchor_drag_alerts("p", "Port", [_anchored(600)], threshold_m=500)
    crit = anchor_drag_alerts("p", "Port", [_anchored(1200)], threshold_m=500)
    assert high[0]["severity"] == "High" and crit[0]["severity"] == "Critical"
    assert high[0]["dedupe_key"] == "anchor_drag:p:123"
    assert "ar" in high[0]["message"] and "en" in high[0]["message"]


def test_haversine_is_sane():
    # 0.01° of latitude is ~1.11 km everywhere
    assert 1100 < haversine_m(51.9, 4.0, 51.91, 4.0) < 1120


# ---------------------------------------------------------------- weather
def _hours(gust, vis):
    return [{"time": "2026-11-07T18:00", "gust_kn": gust, "visibility_m": vis}]


def test_weather_calm_raises_nothing():
    assert weather_alert("p", "Port", _hours(15, 20000), "High") is None
    assert weather_alert("p", "Port", [], "High") is None


def test_weather_gale_and_fog():
    gale = weather_alert("p", "Port", _hours(40, 20000), "Low")
    fog = weather_alert("p", "Port", _hours(10, 500), "High")
    assert gale["evidence"]["gale"] and not gale["evidence"]["fog"]
    assert fog["evidence"]["fog"]
    assert gale["severity"] == "Medium"   # quiet port
    assert fog["severity"] == "High"      # queue already building


# ---------------------------------------------------------------- impact
def test_impact_without_wait_saves_nothing():
    out = estimate_impact({"vessel_queue_length": 0, "avg_waiting_time_hours": 0})
    assert out["jit_per_ship"]["fuel_saved_t"] == 0
    assert out["jit_per_ship"]["recommended_speed_kn"] == SERVICE_SPEED_KN
    assert out["idle"]["idle_cost_usd"] == 0


def test_impact_with_wait_saves_fuel_and_respects_speed_floor():
    out = estimate_impact({"vessel_queue_length": 10, "avg_waiting_time_hours": 30})
    jit = out["jit_per_ship"]
    assert jit["fuel_saved_t"] > 0 and jit["co2_saved_t"] > jit["fuel_saved_t"]
    assert MIN_SPEED_KN <= jit["recommended_speed_kn"] < SERVICE_SPEED_KN
    assert out["idle"]["idle_ship_hours"] == 300
    assert out["is_estimate"] and out["assumptions"]


def test_impact_grows_with_wait():
    short = estimate_impact({"vessel_queue_length": 5, "avg_waiting_time_hours": 4})["jit_per_ship"]["fuel_saved_t"]
    long = estimate_impact({"vessel_queue_length": 5, "avg_waiting_time_hours": 12})["jit_per_ship"]["fuel_saved_t"]
    assert long > short


# ---------------------------------------------------------------- alert workflow
@pytest.fixture
def store(tmp_path):
    return AlertStore(path=str(tmp_path / "alerts.json"))


def _create(store, snapshot=True):
    return store.create(
        alert_type="congestion_escalation", port_id="p", port_name="Port", severity="High",
        title={"en": "t"}, message={"en": "m"}, evidence={}, dedupe_key="k",
        snapshot={"port_name": "Port"} if snapshot else None,
    )


def test_alert_lifecycle(store):
    a = _create(store)
    assert a["status"] == "open" and store.recent_exists("k", 60)
    store.mark_generating(a["id"])
    store.set_advisory(a["id"], {"tier": "High"})
    with pytest.raises(AlertError):
        store.resolve(a["id"])                     # can't resolve with advice awaiting review
    store.review_advisory(a["id"], approve=True)
    assert store.get(a["id"])["status"] == "acknowledged"
    store.resolve(a["id"])
    assert [e["action"] for e in store.get(a["id"])["log"]] == [
        "created", "advisory_requested", "advisory_drafted", "advisory_approved", "resolved"]


def test_alert_invalid_transitions(store):
    a = _create(store, snapshot=False)
    with pytest.raises(AlertError):
        store.review_advisory(a["id"], approve=True)   # nothing to review
    with pytest.raises(AlertError):
        store.mark_generating(a["id"])                 # no snapshot to advise on
    store.acknowledge(a["id"])
    with pytest.raises(AlertError):
        store.acknowledge(a["id"])


def test_alerts_persist_and_recover_interrupted_generation(store):
    a = _create(store)
    store.mark_generating(a["id"])
    reloaded = AlertStore(path=store.path)
    reloaded.load()
    assert reloaded.get(a["id"])["advisory_status"] == "failed"


# ---------------------------------------------------------------- baseline
from app.monitoring.history import MIN_BASELINE_SAMPLES, PortHistory


def test_baseline_needs_enough_samples_then_uses_median(tmp_path):
    h = PortHistory(path=str(tmp_path / "h.json"))
    for i in range(MIN_BASELINE_SAMPLES - 1):
        h.record("p", {"vessel_queue_length": 20, "tier": "Low"})
    assert h.baseline("p") is None
    h.record("p", {"vessel_queue_length": 100, "tier": "Critical"})   # one outlier barely moves a median
    assert h.baseline("p") == 20


# ---------------------------------------------------------------- port configuration
from app.live.aisstream_client import PORTS, _port_for_coords


def test_port_boxes_are_valid_and_do_not_overlap():
    boxes = {pid: info["bbox"] for pid, info in PORTS.items()}
    for pid, ((lat1, lon1), (lat2, lon2)) in boxes.items():
        assert -90 < lat1 < lat2 < 90 and -180 < lon1 < lon2 < 180, pid
        assert PORTS[pid]["berth_count"] > 0
        assert set(PORTS[pid]["name"]) == {"en", "ar"} and set(PORTS[pid]["country"]) == {"en", "ar"}
    ids = list(boxes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            (a1, a2), (a3, a4) = boxes[a]
            (b1, b2), (b3, b4) = boxes[b]
            assert a3 < b1 or b3 < a1 or a4 < b2 or b4 < a2, f"{a} overlaps {b}"


@pytest.mark.parametrize("lat, lon, port", [
    (40.68, -74.15, "new_york_nj"),      # Port Newark / Elizabeth
    (40.46, -73.80, "new_york_nj"),      # Ambrose anchorage
    (39.445, -0.23, "valencia"),         # Valencia north anchorage
    (39.39, -0.25, "valencia"),          # Valencia south anchorage
    (51.95, 1.31, "felixstowe"),         # Port of Felixstowe
    (22.34, 114.11, "hong_kong"),        # Kwai Tsing
    (49.47, 0.15, "le_havre"),           # Port 2000
])
def test_known_locations_map_to_the_right_port(lat, lon, port):
    assert _port_for_coords(lat, lon) == port
