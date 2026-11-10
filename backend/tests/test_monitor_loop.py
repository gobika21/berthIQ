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


# ---------------------------------------------------------------- noise control
def test_restart_does_not_re_report_an_ongoing_level(monitor):
    m, store, hist = monitor
    _learn_normal(hist)
    for _ in range(3):                             # before the restart Rotterdam was already Critical
        hist.record("rotterdam", {"vessel_queue_length": 20, "berth_occupancy_rate": 0.4,
                                  "avg_waiting_time_hours": 2.0, "tier": "Critical"})
    m.seed_from_history()
    m.readings["queue"] = 20
    asyncio.run(m.tick()), asyncio.run(m.tick())
    assert not [a for a in store.list() if a["type"] == "congestion_escalation"]


def test_escalation_closes_itself_when_congestion_clears(monitor):
    m, store, hist = monitor
    _learn_normal(hist)
    asyncio.run(m.tick())
    m.readings["queue"] = 20
    asyncio.run(m.tick()), asyncio.run(m.tick())
    [alert] = [a for a in store.list() if a["type"] == "congestion_escalation"]

    m.readings["queue"] = 1                        # back to normal, confirmed over two checks
    asyncio.run(m.tick()), asyncio.run(m.tick())
    closed = store.get(alert["id"])
    assert closed["status"] == "resolved" and closed["log"][-1]["by"] == "monitor"


def test_open_escalation_is_not_repeated_after_cooldown(monitor, monkeypatch):
    m, store, hist = monitor
    monkeypatch.setitem(mon.COOLDOWN_SECONDS, "congestion_escalation", 0)
    _learn_normal(hist)
    asyncio.run(m.tick())
    m.readings["queue"] = 20
    asyncio.run(m.tick()), asyncio.run(m.tick())
    m.readings["queue"] = 5                        # dips to High, then back to Critical
    asyncio.run(m.tick()), asyncio.run(m.tick())
    m.readings["queue"] = 20
    asyncio.run(m.tick()), asyncio.run(m.tick())
    assert len([a for a in store.list() if a["type"] == "congestion_escalation"]) == 1


def test_one_weather_alert_per_spell_then_it_closes(monitor, monkeypatch):
    m, store, hist = monitor
    monkeypatch.setitem(mon.COOLDOWN_SECONDS, "weather_risk", 0)
    monkeypatch.setattr(mon, "WEATHER_INTERVAL_SECONDS", 0)   # refetch the forecast every tick
    _learn_normal(hist)
    for _ in range(3):
        asyncio.run(m.tick())
    [alert] = [a for a in store.list() if a["type"] == "weather_risk"]

    async def calm(lat, lon, hours=12):
        return [{"time": "2026-11-07T18:00", "gust_kn": 12.0, "visibility_m": 20000}]

    monkeypatch.setattr(mon, "fetch_forecast", calm)
    asyncio.run(m.tick())
    assert store.get(alert["id"])["status"] == "resolved"


def test_housekeeping_closes_stale_and_legacy_alerts_only(monitor):
    m, store, hist = monitor

    def make(alert_type, evidence, age_hours=0, demo=False):
        a = store.create(alert_type=alert_type, port_id="rotterdam", port_name="Rotterdam", severity="High",
                         title={"en": "t"}, message={"en": "m"}, evidence=evidence, dedupe_key=alert_type,
                         snapshot={"port_name": "Rotterdam"}, demo=demo)
        a["created_at"] -= age_hours * 3600
        return a

    legacy_drag = make("anchor_drag", {"drift_m": 600, "speed_knots": 7.9})
    real_drag = make("anchor_drag", {"drift_m": 900, "speed_knots": 1.2, "confirmed_after_ticks": 2})
    stale = make("congestion_escalation", {}, age_hours=30)
    fresh = make("congestion_escalation", {}, age_hours=2)
    awaiting_review = make("weather_risk", {}, age_hours=30)
    store.mark_generating(awaiting_review["id"]); store.set_advisory(awaiting_review["id"], {"tier": "High"})
    demo = make("anchor_drag", {}, demo=True)

    m.housekeeping()
    status = {k: store.get(a["id"])["status"] for k, a in {
        "legacy_drag": legacy_drag, "real_drag": real_drag, "stale": stale, "fresh": fresh,
        "awaiting_review": awaiting_review, "demo": demo}.items()}
    assert status == {"legacy_drag": "resolved", "real_drag": "open", "stale": "resolved", "fresh": "open",
                      "awaiting_review": "resolved", "demo": "open"}
    assert store.get(awaiting_review["id"])["advisory_status"] == "expired"


def test_newer_alert_replaces_older_ones_for_the_same_port(monitor):
    m, store, hist = monitor
    ids = [store.create(alert_type="congestion_escalation", port_id="rotterdam", port_name="Rotterdam",
                        severity=sev, title={"en": "t"}, message={"en": "m"}, evidence={}, dedupe_key=sev,
                        snapshot=None)["id"] for sev in ("High", "Critical")]
    other_port = store.create(alert_type="congestion_escalation", port_id="antwerp", port_name="Antwerp",
                              severity="High", title={"en": "t"}, message={"en": "m"}, evidence={},
                              dedupe_key="a", snapshot=None)
    store.get(ids[0])["created_at"] -= 60
    m.housekeeping()
    assert [store.get(i)["status"] for i in ids] == ["resolved", "open"]
    assert store.get(other_port["id"])["status"] == "open"
