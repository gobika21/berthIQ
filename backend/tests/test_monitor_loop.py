"""Drives Monitor.tick() with a fake AIS cache and forecast to check the whole detect → alert path."""

import asyncio

import pytest

import app.monitoring.monitor as mon
from app.monitoring.alerts import AlertStore
from app.monitoring.history import PortHistory


@pytest.fixture
def monitor(tmp_path, monkeypatch):
    store = AlertStore(path=str(tmp_path / "alerts.json"))
    hist = PortHistory(path=str(tmp_path / "history.json"))
    monkeypatch.setattr(mon, "alerts", store)
    monkeypatch.setattr(mon, "history", hist)
    monkeypatch.setattr(mon, "AUTO_ADVISORY", False)  # no LLM calls from this test
    monkeypatch.setattr(mon.cache, "connected", True)

    # Only Rotterdam has (fake) data; every other port is reported as still warming up.
    readings = {"queue": 1}

    def fake_snapshot(port_id, lang="en"):
        return {
            "port_name": port_id.title(),
            "berth_occupancy_rate": 0.4,
            "vessel_queue_length": readings["queue"] if port_id == "rotterdam" else 0,
            "avg_waiting_time_hours": 2.0,
            "warming_up": port_id != "rotterdam",
        }

    # A ship dragging steadily: further from its anchor point on every check.
    drag_reads = iter(range(900, 100000, 100))

    def drifting(port_id):
        if port_id != "rotterdam":
            return []
        return [{"mmsi": "244000001", "lat": 51.95, "lon": 4.05, "anchor_lat": 51.94, "anchor_lon": 4.05,
                 "drift_m": next(drag_reads), "speed_knots": 1.4}]

    async def fake_forecast(lat, lon, hours=12):
        return [{"time": "2026-11-07T18:00", "gust_kn": 41.0, "visibility_m": 15000}]

    monkeypatch.setattr(mon, "build_port_snapshot", fake_snapshot)
    monkeypatch.setattr(mon.cache, "anchored_vessels", drifting)
    monkeypatch.setattr(mon, "fetch_forecast", fake_forecast)

    m = mon.Monitor()
    m.readings = readings
    return m, store, hist


def _learn_normal(hist, queue=1, n=40):
    for _ in range(n):
        hist.record("rotterdam", {"vessel_queue_length": queue, "berth_occupancy_rate": 0.4,
                                  "avg_waiting_time_hours": 2.0, "tier": "Low"})


def test_monitor_raises_each_alert_type_once(monitor):
    m, store, hist = monitor
    _learn_normal(hist)

    asyncio.run(m.tick())                      # Low baseline; the gale fires immediately...
    assert sorted(a["type"] for a in store.list()) == ["weather_risk"]
    asyncio.run(m.tick())                      # ...anchor drag only once the drift keeps growing
    assert sorted(a["type"] for a in store.list()) == ["anchor_drag", "weather_risk"]

    m.readings["queue"] = 20                   # queue jumps to Critical...
    asyncio.run(m.tick())                      # ...first sighting: not yet confirmed
    assert not [a for a in store.list() if a["type"] == "congestion_escalation"]
    asyncio.run(m.tick())                      # confirmed on the second consecutive tick

    escalations = [a for a in store.list() if a["type"] == "congestion_escalation"]
    assert len(escalations) == 1
    assert escalations[0]["severity"] == "Critical"
    assert escalations[0]["snapshot"]["situation"]          # context ready for the agents
    assert escalations[0]["advisory_status"] == "none"      # AUTO_ADVISORY off in this test

    # Cooldowns: repeated ticks don't duplicate any alert
    asyncio.run(m.tick())
    assert len(store.list()) == 3

    # History recorded one sample per tick for the live port only (plus the 40 learned ones)
    assert len(hist.samples("rotterdam")) == 45
    assert hist.samples("singapore") == []
    assert m.latest["rotterdam"]["tier"] == "Critical"


def test_monitor_skips_everything_without_live_feed(monitor, monkeypatch):
    m, store, hist = monitor
    monkeypatch.setattr(mon.cache, "connected", False)
    asyncio.run(m.tick())
    assert store.list() == [] and hist.samples("rotterdam") == []


def test_saturated_berth_estimate_does_not_drive_live_tier(monitor, monkeypatch):
    m, store, hist = monitor
    original = mon.build_port_snapshot

    def full_berths(port_id, lang="en"):
        return {**original(port_id, lang), "berth_occupancy_rate": 1.0}

    monkeypatch.setattr(mon, "build_port_snapshot", full_berths)
    asyncio.run(m.tick())
    assert m.latest["rotterdam"]["tier"] == "Low"
    assert "berth_occupancy_rate" not in m.latest["rotterdam"]["metric_tiers"]


def test_busy_port_is_judged_against_its_own_normal(monitor):
    m, store, hist = monitor
    for _ in range(40):                                  # Rotterdam usually has ~20 ships waiting
        hist.record("rotterdam", {"vessel_queue_length": 20, "berth_occupancy_rate": 0.4,
                                  "avg_waiting_time_hours": 2.0, "tier": "Low"})
    m.readings["queue"] = 21                             # globally "Critical", but normal here
    asyncio.run(m.tick())
    assert m.latest["rotterdam"]["tier"] == "Low"

    m.readings["queue"] = 45                             # more than double the usual level
    asyncio.run(m.tick()), asyncio.run(m.tick())
    escalation = [a for a in store.list() if a["type"] == "congestion_escalation"]
    assert escalation and escalation[0]["severity"] == "Critical"
    assert "usual for this port: about 20" in escalation[0]["message"]["en"]


def test_no_escalation_alerts_before_port_normal_is_known(monitor):
    m, store, hist = monitor
    m.readings["queue"] = 30                       # "Critical" by global thresholds
    for _ in range(3):
        asyncio.run(m.tick())
    assert m.latest["rotterdam"]["tier"] == "Critical"      # still shown on the board...
    assert not [a for a in store.list() if a["type"] == "congestion_escalation"]   # ...but no alert
