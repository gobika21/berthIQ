from dotenv import load_dotenv

load_dotenv()

import logging
import os
import re
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.advisory_service import run_advisory
from app.agents.classification import classify_snapshot
from app.agents.monitoring import SnapshotValidationError
from app import ai_quota
from app.ai_quota import claim_free_run, free_runs_left, server_key_available
from app.claude_client import set_access
from app.impact import estimate_impact
from app.live.aisstream_client import (
    PORTS,
    AISStreamError,
    build_port_snapshot,
    get_all_live_vessel_queues,
    get_live_vessel_queue,
    list_ports,
    start_collector,
    stop_collector,
)
from app.models.schema import PortSnapshot
from app.monitoring.alerts import ALERT_STATUSES, AlertError, alerts
from app.monitoring.detectors import escalation_alert
from app.monitoring.history import history
from app.monitoring.monitor import monitor, pipeline_snapshot
from app.scenarios import SCENARIOS

logger = logging.getLogger("berthiq")

# Set BERTHIQ_DISABLE_BACKGROUND=1 (tests, one-off scripts) to skip the AIS
# collector and monitor loop.
BACKGROUND = os.environ.get("BERTHIQ_DISABLE_BACKGROUND") != "1"
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
LLM_RATE_LIMIT_PER_MINUTE = int(os.environ.get("LLM_RATE_LIMIT_PER_MINUTE", 6))
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if BACKGROUND:
        start_collector()
        monitor.start()
    try:
        yield
    finally:
        if BACKGROUND:
            monitor.stop()
            stop_collector()


app = FastAPI(title="BerthIQ", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Anthropic-Key"],
)


# ---------------------------------------------------------------- rate limiting
# Every endpoint that calls the Claude API costs money, so each client IP gets a
# small per-minute allowance. In-memory is enough for a single-instance deploy.
_llm_calls: dict[str, deque[float]] = defaultdict(deque)


def enforce_llm_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    window = _llm_calls[client]
    now = time.time()
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= LLM_RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="Too many AI requests — please wait a minute and try again.")
    window.append(now)


# ---------------------------------------------------------------- who pays for Claude
# A visitor may send their own Anthropic key in the X-Anthropic-Key header. It is used
# for that request only: never stored, logged or returned. Without one, the run comes
# out of the server's small free daily quota; once that is used up the agents still
# answer, with rule-based advice (ai_status "fallback", ai_error "free_quota_used").
_KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,200}$")
def choose_claude_access(request: Request) -> None:
    """Decide whose key pays for this request's Claude calls (see claude_client.set_access)."""
    own_key = request.headers.get("x-anthropic-key", "").strip()
    if own_key:
        if not _KEY_PATTERN.match(own_key):
            raise HTTPException(status_code=400, detail="That doesn't look like an Anthropic API key (it should start with sk-ant-).")
        set_access(("own", own_key))
    elif not server_key_available():
        set_access(("none", "no_key"))
    elif claim_free_run():
        set_access(("server",))
    else:
        set_access(("none", "free_quota_used"))


def _run_advisory_or_http_error(snapshot: dict) -> dict:
    try:
        return run_advisory(snapshot)
    except SnapshotValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Advisory pipeline failed")
        raise HTTPException(status_code=502, detail="The AI agents could not produce an advisory. Please try again.") from exc


# ---------------------------------------------------------------- basics
@app.get("/health")
def health():
    return {"status": "ok", "monitor_last_tick": monitor.last_tick_at}


@app.get("/ai/quota")
def get_ai_quota():
    """How many free AI runs (on the server's key) are left today, for all visitors together."""
    return {"free_runs_per_day": ai_quota.FREE_AI_RUNS_PER_DAY if server_key_available() else 0, "free_runs_left": free_runs_left()}


@app.get("/scenarios")
def list_scenarios():
    return SCENARIOS


# ---------------------------------------------------------------- live data
def _with_live_tier(live: dict, lang: str = "en") -> dict:
    """Add the current congestion tier, 24 h trend and idle-cost estimate to a live reading."""
    port_id = live["port_id"]
    if not live["live_coverage"] or live["warming_up"]:
        # A port we can't see (or haven't watched long enough) has no trustworthy tier.
        return {**live, "tier": None, "metric_tiers": None, "trend": history.trend(port_id), "idle_cost_usd": None,
                "queue_baseline": None}
    baseline = history.baseline(port_id)
    snap = pipeline_snapshot(build_port_snapshot(port_id, lang=lang), baseline)
    cls = classify_snapshot(snap)
    return {
        **live,
        "avg_waiting_time_hours": snap["avg_waiting_time_hours"],
        "berth_occupancy_rate": snap["berth_occupancy_rate"],
        "tier": cls["tier"],
        "metric_tiers": cls["metric_tiers"],
        "trend": history.trend(port_id),
        "idle_cost_usd": estimate_impact(snap)["idle"]["idle_cost_usd"],
        "queue_baseline": baseline,
    }


@app.get("/live/ports")
def live_ports(lang: str = "en"):
    """List of ports tracked by the live board, with whether each has confirmed AIS coverage."""
    return list_ports(lang=lang)


@app.get("/live/vessel-queue")
def live_vessel_queue(port: str, positions: bool = False, lang: str = "en"):
    """Live reading for one port: queue, ships at berth, live tier and 24 h trend.

    Pass `positions=true` to include each tracked ship's lat/lon for the map.
    """
    try:
        return _with_live_tier(get_live_vessel_queue(port, include_positions=positions, lang=lang), lang)
    except AISStreamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/live/vessel-queue/all")
def live_vessel_queue_all(lang: str = "en"):
    """Live readings for every tracked port — powers the board view."""
    return [_with_live_tier(live, lang) for live in get_all_live_vessel_queues(lang=lang)]


@app.get("/live/history")
def live_history(port: str, hours: float = 24):
    """Readings the monitor recorded for a port (every few minutes, up to 24 h)."""
    if port not in PORTS:
        raise HTTPException(status_code=400, detail=f"Unknown port '{port}'")
    return history.samples(port, hours=min(max(hours, 0.5), 24))


# ---------------------------------------------------------------- advisories
@app.post("/advisory")
def advisory(request: Request, snapshot: PortSnapshot):
    enforce_llm_rate_limit(request)
    choose_claude_access(request)
    data = dict(snapshot)
    data.pop("situation", None)  # only the monitor may add alert context to the prompt
    return _run_advisory_or_http_error(data)


@app.get("/live/advisory")
def live_advisory(request: Request, port: str, lang: str = "en"):
    """Run the full agent pipeline on the current live AIS snapshot for a port."""
    try:
        snapshot = build_port_snapshot(port, lang=lang)
    except AISStreamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    enforce_llm_rate_limit(request)
    choose_claude_access(request)
    result = _run_advisory_or_http_error({**pipeline_snapshot(snapshot), "language": lang})
    return {"snapshot": snapshot, **result}


# ---------------------------------------------------------------- alerts
def _alert_or_404(alert_id: str) -> dict:
    try:
        return alerts.get(alert_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Alert not found") from exc


def _apply(action, alert_id: str, note: str | None):
    _alert_or_404(alert_id)
    try:
        return action(alert_id, note=note)
    except AlertError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/alerts")
def list_alerts(status: str | None = None, port: str | None = None):
    if status is not None and status not in ALERT_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {ALERT_STATUSES}")
    return alerts.list(status=status, port_id=port)


@app.get("/alerts/{alert_id}")
def get_alert(alert_id: str):
    return _alert_or_404(alert_id)


@app.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: str, note: str | None = Body(None, embed=True)):
    return _apply(alerts.acknowledge, alert_id, note)


@app.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str, note: str | None = Body(None, embed=True)):
    return _apply(alerts.resolve, alert_id, note)


@app.post("/alerts/{alert_id}/approve")
def approve_advisory(alert_id: str, note: str | None = Body(None, embed=True)):
    return _apply(lambda i, note: alerts.review_advisory(i, approve=True, note=note), alert_id, note)


@app.post("/alerts/{alert_id}/reject")
def reject_advisory(alert_id: str, note: str | None = Body(None, embed=True)):
    return _apply(lambda i, note: alerts.review_advisory(i, approve=False, note=note), alert_id, note)


@app.post("/alerts/{alert_id}/advisory")
async def request_advisory(request: Request, alert_id: str):
    """Ask the agents to draft (or re-draft) advice for an alert; it then awaits approval."""
    _alert_or_404(alert_id)
    enforce_llm_rate_limit(request)
    choose_claude_access(request)  # inherited by the background drafting task
    try:
        monitor.schedule_advisory(alert_id)
    except AlertError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return alerts.get(alert_id)


# ---------------------------------------------------------------- demo
@app.post("/demo/replay")
async def demo_replay(request: Request, port: str = "rotterdam"):
    """Raise a clearly-labelled demo escalation so the alert → advice → approval flow
    can be shown even when every real port is calm. Demo alerts are flagged `demo: true`."""
    if not DEMO_MODE:
        raise HTTPException(status_code=404, detail="Demo mode is disabled")
    if port not in PORTS:
        raise HTTPException(status_code=400, detail=f"Unknown port '{port}'")
    enforce_llm_rate_limit(request)
    choose_claude_access(request)

    port_name = PORTS[port]["name"]["en"]
    snap = {**SCENARIOS["high"], "port_name": port_name}
    cls = classify_snapshot(snap)
    spec = escalation_alert(port, port_name, "Medium", cls["tier"], cls, snap)
    spec["title"] = {k: f"[Demo] {v}" for k, v in spec["title"].items()}
    # Drafted below with this visitor's access (their key or a free run), not the monitor's.
    alert = monitor.raise_alert(port, port_name, spec, snap, demo=True, auto_advise=False)
    if alert and alert["advisory_status"] == "none":
        monitor.schedule_advisory(alert["id"])
    return alerts.get(alert["id"])
