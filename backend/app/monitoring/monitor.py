"""The autonomous loop: watch every live port, detect events, raise alerts, draft advice.

Every MONITOR_INTERVAL_SECONDS it:
  1. builds a snapshot for each port with live AIS coverage,
  2. classifies it (rule-based, no LLM cost) and records it in the 24 h history,
  3. runs the detectors (congestion escalation, anchor drag, weather risk),
  4. stores new alerts (with cooldowns so one event isn't raised repeatedly), and
  5. for congestion and weather alerts, asks the agents for an advisory that then
     waits for a human to approve it.

Step 5 calls the Claude API, so it's capped per hour (AUTO_ADVISORY_MAX_PER_HOUR)
and can be switched off entirely with AUTO_ADVISORY=0.
"""

import asyncio
import logging
import os
import time
from collections import deque

from app.advisory_service import run_advisory
from app.agents.classification import LIVE_TIER_METRICS, classify_snapshot
from app.live.aisstream_client import PORTS, build_port_snapshot, cache
from app.monitoring.alerts import AlertError, alerts
from app.monitoring.detectors import (
    MIN_ALERT_TIER, AnchorDragTracker, TierTracker, anchor_drag_alerts, drag_candidates, escalation_alert,
    tier_index, weather_alert,
)
from app.monitoring.history import history
from app.monitoring.weather import fetch_forecast

logger = logging.getLogger(__name__)

MONITOR_INTERVAL_SECONDS = float(os.environ.get("MONITOR_INTERVAL_SECONDS", 120))
WEATHER_INTERVAL_SECONDS = float(os.environ.get("WEATHER_INTERVAL_SECONDS", 1800))
AUTO_ADVISORY = os.environ.get("AUTO_ADVISORY", "1") == "1"
AUTO_ADVISORY_MAX_PER_HOUR = int(os.environ.get("AUTO_ADVISORY_MAX_PER_HOUR", 6))
ADVISORY_LANGUAGE = os.environ.get("ADVISORY_LANGUAGE", "en")

COOLDOWN_SECONDS = {
    "congestion_escalation": 3 * 3600,
    "anchor_drag": 6 * 3600,
    "weather_risk": 6 * 3600,
}
ADVISED_TYPES = ("congestion_escalation", "weather_risk")
# An alert nobody has touched for this long is no longer current: close it automatically.
ALERT_MAX_AGE_SECONDS = float(os.environ.get("ALERT_MAX_AGE_HOURS", 24)) * 3600

SITUATION_NOTE = {
    "congestion_escalation": "Congestion has just escalated at this port and has been confirmed over consecutive checks.",
    "weather_risk": "Weather risk forecast: {detail} Factor this into the advice (pilotage or berthing may pause).",
}


def pipeline_snapshot(port_snapshot: dict, queue_baseline: float | None = None) -> dict:
    """A live AIS reading as agent input. Only the live-measured metrics drive the tier,
    and the queue is judged against the port's own usual level once that's known."""
    keys = ("port_name", "berth_occupancy_rate", "vessel_queue_length", "avg_waiting_time_hours")
    snap = {**{k: port_snapshot[k] for k in keys}, "tier_metrics": list(LIVE_TIER_METRICS)}
    if queue_baseline is not None:
        snap["queue_baseline"] = queue_baseline
    return snap


class Monitor:
    def __init__(self):
        self.tracker = TierTracker()
        self.drag_tracker = AnchorDragTracker()
        self.latest: dict[str, dict] = {}
        self._weather: dict[str, tuple[float, list[dict]]] = {}
        self._advisory_times: deque[float] = deque()
        self.last_tick_at: float | None = None
        self._task: asyncio.Task | None = None
        self._pending: set[asyncio.Task] = set()

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> None:
        history.load()
        alerts.load()
        self.seed_from_history()
        self.housekeeping()
        if self._task is None:
            self._task = asyncio.create_task(self._run_forever())

    def stop(self) -> None:
        history.save()
        alerts.save()
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def seed_from_history(self) -> None:
        """Pick up each port's last recorded tier, so a restart compares against it."""
        for port_id in PORTS:
            samples = history.samples(port_id, hours=1)
            if samples:
                self.tracker.seed(port_id, samples[-1]["tier"])

    def housekeeping(self) -> None:
        """Close alerts that are no longer current, so the list shows only what needs attention."""
        now = time.time()
        newest_seen: set[tuple[str, str]] = set()
        for a in alerts.list():  # newest first
            if a["status"] == "resolved" or a.get("demo"):
                continue
            key = (a["port_id"], a["type"])
            if a["type"] == "anchor_drag" and "confirmed_after_ticks" not in (a.get("evidence") or {}):
                alerts.auto_resolve(a["id"], "Raised by an earlier anchor-drag detector that also flagged ordinary "
                                             "swinging and ships under way; closed automatically.")
            elif a["type"] in ADVISED_TYPES and key in newest_seen:
                alerts.auto_resolve(a["id"], "Replaced by a newer alert for this port; closed automatically.")
            elif a["status"] == "open" and now - a["created_at"] > ALERT_MAX_AGE_SECONDS:
                alerts.auto_resolve(a["id"], f"No action for {ALERT_MAX_AGE_SECONDS / 3600:g} hours; "
                                             "closed automatically as no longer current.")
            newest_seen.add(key)

    async def _run_forever(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # never let one bad tick kill monitoring
                logger.exception("Monitor tick failed")
            await asyncio.sleep(MONITOR_INTERVAL_SECONDS)

    # ---------------------------------------------------------------- one pass
    async def tick(self) -> None:
        if not cache.connected:
            return  # no live feed: nothing trustworthy to monitor
        for port_id, info in PORTS.items():
            if not info["live_coverage"]:
                continue
            port_snap = build_port_snapshot(port_id)
            if port_snap["warming_up"]:
                continue
            await self._check_port(port_id, port_snap)
        self.housekeeping()
        self.last_tick_at = time.time()
        history.save()

    async def _check_port(self, port_id: str, port_snap: dict) -> None:
        # Baseline from history *before* this reading is added, so a sudden spike
        # isn't partly averaged into its own "usual" level.
        snap = pipeline_snapshot(port_snap, history.baseline(port_id))
        port_name = snap["port_name"]
        cls = classify_snapshot(snap)

        history.record(port_id, {
            "berth_occupancy_rate": snap["berth_occupancy_rate"],
            "vessel_queue_length": snap["vessel_queue_length"],
            "avg_waiting_time_hours": snap["avg_waiting_time_hours"],
            "tier": cls["tier"],
        })
        self.latest[port_id] = {"tier": cls["tier"], "metric_tiers": cls["metric_tiers"], "at": time.time()}

        escalation = self.tracker.update(port_id, cls["tier"])
        # "Escalation" means worse than this port's normal — so no alerts until that
        # normal is known. Global thresholds alone would flag busy ports (e.g.
        # Singapore's anchorage) as critical on an ordinary day.
        if escalation and snap.get("queue_baseline") is not None:
            # Already alerted at this level or worse and still open: nothing new to say.
            if not any(tier_index(a["severity"]) >= tier_index(escalation[1])
                       for a in alerts.active(port_id, "congestion_escalation")):
                spec = escalation_alert(port_id, port_name, escalation[0], escalation[1], cls, snap)
                self.raise_alert(port_id, port_name, spec, snap)
        confirmed = self.tracker.confirmed(port_id)
        if confirmed and tier_index(confirmed) < tier_index(MIN_ALERT_TIER):
            for a in alerts.active(port_id, "congestion_escalation"):
                alerts.auto_resolve(a["id"], f"Congestion back to {confirmed}; closed automatically.")

        dragging = self.drag_tracker.update(port_id, drag_candidates(cache.anchored_vessels(port_id)))
        for spec in anchor_drag_alerts(port_id, port_name, dragging):
            self.raise_alert(port_id, port_name, spec, None)

        forecast = await self._forecast(port_id)
        spec = weather_alert(port_id, port_name, forecast, self.tracker.confirmed(port_id) or cls["tier"])
        active_weather = alerts.active(port_id, "weather_risk")
        if spec and not active_weather:  # one alert per spell of bad weather, not one every 6 hours
            self.raise_alert(port_id, port_name, spec, snap)
        elif not spec and forecast:
            for a in active_weather:
                alerts.auto_resolve(a["id"], "Forecast no longer shows gale or fog; closed automatically.")

    async def _forecast(self, port_id: str) -> list[dict]:
        fetched_at, forecast = self._weather.get(port_id, (0.0, []))
        if time.time() - fetched_at < WEATHER_INTERVAL_SECONDS:
            return forecast
        (lat_min, lon_min), (lat_max, lon_max) = PORTS[port_id]["bbox"]
        forecast = await fetch_forecast((lat_min + lat_max) / 2, (lon_min + lon_max) / 2)
        self._weather[port_id] = (time.time(), forecast)
        return forecast

    # ---------------------------------------------------------------- alerts + advice
    def raise_alert(self, port_id: str, port_name: str, spec: dict, snapshot: dict | None,
                    demo: bool = False) -> dict | None:
        alert_type = spec["alert_type"]
        if not demo and alerts.recent_exists(spec["dedupe_key"], COOLDOWN_SECONDS[alert_type]):
            return None

        advise_snapshot = None
        if snapshot and alert_type in ADVISED_TYPES:
            detail = spec["message"]["en"]
            note = SITUATION_NOTE[alert_type].format(detail=detail)
            advise_snapshot = {**snapshot, "language": ADVISORY_LANGUAGE, "situation": note}

        alert = alerts.create(
            alert_type=alert_type, port_id=port_id, port_name=port_name, severity=spec["severity"],
            title=spec["title"], message=spec["message"], evidence=spec["evidence"],
            dedupe_key=spec["dedupe_key"], snapshot=advise_snapshot, demo=demo,
        )
        logger.info("Alert raised: %s (%s)", spec["title"]["en"], alert["id"])

        if advise_snapshot and AUTO_ADVISORY and self._advisory_budget_ok():
            self.schedule_advisory(alert["id"])
        return alert

    def _advisory_budget_ok(self) -> bool:
        cutoff = time.time() - 3600
        while self._advisory_times and self._advisory_times[0] < cutoff:
            self._advisory_times.popleft()
        if len(self._advisory_times) >= AUTO_ADVISORY_MAX_PER_HOUR:
            logger.info("Auto-advisory budget reached; alert left for manual advice")
            return False
        self._advisory_times.append(time.time())
        return True

    def schedule_advisory(self, alert_id: str) -> None:
        alerts.mark_generating(alert_id)  # raises AlertError if not allowed
        task = asyncio.create_task(self._generate(alert_id))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _generate(self, alert_id: str) -> None:
        snapshot = alerts.get(alert_id)["snapshot"]
        try:
            advisory = await asyncio.to_thread(run_advisory, snapshot)
        except Exception as exc:
            logger.warning("Advisory generation failed for %s: %s", alert_id, exc)
            alerts.set_advisory(alert_id, None, error=str(exc) or exc.__class__.__name__)
            return
        alerts.set_advisory(alert_id, advisory)


monitor = Monitor()

__all__ = ["monitor", "Monitor", "AlertError", "pipeline_snapshot"]
