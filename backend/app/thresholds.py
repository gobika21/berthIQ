"""Congestion tier thresholds.

Placeholder values based on typical UNCTAD-style port KPIs — replace with the
exact thresholds validated in the dissertation before the demo.
"""

TIER_THRESHOLDS = {
    "berth_occupancy_rate": {"Low": 0.5, "Medium": 0.7, "High": 0.85},
    "vessel_queue_length": {"Low": 3, "Medium": 8, "High": 15},
    "avg_waiting_time_hours": {"Low": 4, "Medium": 12, "High": 24},
}


# Port-relative queue tiers: once a port has enough history, its queue is judged
# against its own usual level (median) rather than a single global count — a queue
# of 20 is routine at Singapore's anchorage but serious at a small terminal.
# Values are multiples of the port's usual queue.
RELATIVE_QUEUE_THRESHOLDS = {"Low": 1.2, "Medium": 1.5, "High": 2.0}
# A port that's usually almost empty would otherwise look "3× normal" with 3 ships.
MIN_QUEUE_BASELINE = 3.0


def effective_thresholds(metric: str, queue_baseline: float | None = None) -> dict:
    """Thresholds actually applied to a metric, in its own units (ships, hours, fraction)."""
    if metric == "vessel_queue_length" and queue_baseline is not None:
        base = max(queue_baseline, MIN_QUEUE_BASELINE)
        return {tier: round(base * mult, 1) for tier, mult in RELATIVE_QUEUE_THRESHOLDS.items()}
    return TIER_THRESHOLDS[metric]


def classify_metric(value: float, bounds: dict) -> str:
    if value < bounds["Low"]:
        return "Low"
    if value < bounds["Medium"]:
        return "Medium"
    if value < bounds["High"]:
        return "High"
    return "Critical"
