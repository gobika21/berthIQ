"""One entry point for running the agent pipeline, used by the API and the monitor.

Wraps the raw LangGraph result with the evidence behind the tier (so the UI can
answer "why?"), impact estimates (so every advisory shows what it's worth), and
what the advisory cost to produce. If Claude is unavailable the user still gets the
rule-based congestion level and evidence, with standard advice clearly marked.
"""

import logging
import time

import anthropic

from app.agents.classification import classify_snapshot
from app.agents.monitoring import SnapshotValidationError, monitoring_node
from app.agents.precedent_retrieval import precedent_retrieval_node
from app.claude_client import track_usage
from app.fallback import fallback_advice
from app.graph import run_pipeline
from app.impact import estimate_impact

logger = logging.getLogger("berthiq.advisory")

METRICS = ("berth_occupancy_rate", "vessel_queue_length", "avg_waiting_time_hours")

# Failures that mean "Claude couldn't help this time", not "the request is wrong":
# API errors (incl. timeouts and connection errors, after the SDK's retries), a reply
# that still failed validation after our own retry (ValueError), or a missing API key.
CLAUDE_FAILURES = (anthropic.APIError, ValueError, RuntimeError)


def _rule_based_result(snapshot: dict) -> dict:
    """Everything the pipeline produces without Claude: tier, evidence, precedents, template advice."""
    state = monitoring_node({"snapshot": dict(snapshot)})
    clean, language = state["snapshot"], state["language"]
    cls = classify_snapshot(clean, language)
    precedents = precedent_retrieval_node({
        "snapshot": clean, "tier": cls["tier"], "tier_reasoning": cls["tier_reasoning"],
        "driving_metrics": cls["driving_metrics"],
    })["precedents"]
    recommendations, advisories = fallback_advice(clean, cls["tier"], language)
    return {**cls, "snapshot": clean, "precedents": precedents,
            "recommendations": recommendations, "advisories": advisories}


def run_advisory(snapshot: dict) -> dict:
    start = time.perf_counter()
    ai_status, ai_error = "ok", None
    with track_usage() as usage:
        try:
            result = run_pipeline(snapshot)
        except SnapshotValidationError:
            raise  # bad input is the caller's problem, not a reason to fall back
        except CLAUDE_FAILURES as exc:
            logger.warning("Claude unavailable, using rule-based advice: %s: %s", type(exc).__name__, exc)
            ai_status, ai_error = "fallback", type(exc).__name__
            result = _rule_based_result(snapshot)

    clean = result["snapshot"]  # validated/normalised by the Monitoring agent
    cost = {**usage.summary(), "latency_s": round(time.perf_counter() - start, 2)}
    logger.info(
        "Advisory for %s: %s, %d Claude calls, %d in / %d out tokens, $%.4f, %.1fs",
        clean.get("port_name"), ai_status, cost["claude_calls"], cost["input_tokens"],
        cost["output_tokens"], cost["cost_usd"], cost["latency_s"],
    )

    evidence = {
        "metrics": {m: clean[m] for m in METRICS},
        # Metrics missing here were shown but not used for the tier (e.g. a rough live estimate).
        "metric_tiers": result.get("metric_tiers", {}),
        "thresholds": result["thresholds"],  # effective values, port-relative for the queue when known
        "queue_baseline": clean.get("queue_baseline"),
        "driving_metrics": result.get("driving_metrics", []),
        "precedent_ids": [p["id"] for p in result.get("precedents", [])],
    }

    return {
        "tier": result["tier"],
        "tier_reasoning": result["tier_reasoning"],
        "precedents": result.get("precedents", []),
        "recommendations": result["recommendations"],
        "advisories": result["advisories"],
        "evidence": evidence,
        "impact": estimate_impact(clean),
        "ai_status": ai_status,  # "ok" or "fallback" (standard advice, Claude unavailable)
        "ai_error": ai_error,
        "usage": cost,
    }
