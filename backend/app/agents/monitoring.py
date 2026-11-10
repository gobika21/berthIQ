"""Monitoring agent: validates and normalizes an incoming port snapshot."""

import math

from app.models.schema import AdvisoryState, PortSnapshot

REQUIRED_FIELDS = ("port_name", "berth_occupancy_rate", "vessel_queue_length", "avg_waiting_time_hours")
SUPPORTED_LANGUAGES = ("en", "ar")


class SnapshotValidationError(ValueError):
    """The incoming snapshot is malformed — a client error, not a pipeline failure."""


def _number(snapshot: PortSnapshot, field: str) -> float:
    value = snapshot[field]
    # bool is a subclass of int in Python, so exclude it explicitly
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SnapshotValidationError(f"'{field}' must be a finite number, got {value!r}")
    return value


def monitoring_node(state: AdvisoryState) -> AdvisoryState:
    snapshot: PortSnapshot = state["snapshot"]

    missing = [f for f in REQUIRED_FIELDS if f not in snapshot]
    if missing:
        raise SnapshotValidationError(f"Snapshot missing fields: {missing}")

    if not isinstance(snapshot["port_name"], str) or not snapshot["port_name"].strip():
        raise SnapshotValidationError("'port_name' must be a non-empty string")

    occupancy = _number(snapshot, "berth_occupancy_rate")
    if not 0 <= occupancy <= 1:
        raise SnapshotValidationError(
            f"'berth_occupancy_rate' is a fraction between 0 and 1 (e.g. 0.85 for 85%), got {occupancy}"
        )

    queue = _number(snapshot, "vessel_queue_length")
    if queue < 0 or queue != int(queue):
        raise SnapshotValidationError(f"'vessel_queue_length' must be a whole number >= 0, got {queue}")

    waiting = _number(snapshot, "avg_waiting_time_hours")
    if waiting < 0:
        raise SnapshotValidationError(f"'avg_waiting_time_hours' must be >= 0, got {waiting}")

    language = snapshot.get("language", "en")
    if language not in SUPPORTED_LANGUAGES:
        raise SnapshotValidationError(f"'language' must be one of {SUPPORTED_LANGUAGES}, got {language!r}")

    situation = snapshot.get("situation")
    if situation is not None and (not isinstance(situation, str) or len(situation) > 500):
        raise SnapshotValidationError("'situation' must be a string of at most 500 characters")

    tier_metrics = snapshot.get("tier_metrics")
    if tier_metrics is not None and (
        not isinstance(tier_metrics, list) or not tier_metrics or not set(tier_metrics) <= set(REQUIRED_FIELDS[1:])
    ):
        raise SnapshotValidationError(f"'tier_metrics' must be a non-empty list drawn from {list(REQUIRED_FIELDS[1:])}")

    baseline = snapshot.get("queue_baseline")
    if baseline is not None and (
        isinstance(baseline, bool) or not isinstance(baseline, (int, float)) or not math.isfinite(baseline) or baseline < 0
    ):
        raise SnapshotValidationError(f"'queue_baseline' must be a non-negative number, got {baseline!r}")

    normalized = {**snapshot, "vessel_queue_length": int(queue)}
    return {"snapshot": normalized, "language": language}
