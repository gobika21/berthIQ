"""Rolling 7-day history of each port's live readings, written by the monitor loop.

Used for the 24 h trend sparklines and for each port's usual-queue baseline."""

import os
import statistics
import time

from app.monitoring.storage import data_path, load_json, save_json

# Keep a week so each port's "usual" queue reflects normal weekly rhythms, not just today.
RETENTION_SECONDS = 7 * 24 * 3600
# Don't trust a baseline until the monitor has watched the port for about an hour
# (30 samples at the default 2-minute interval).
MIN_BASELINE_SAMPLES = int(os.environ.get("MIN_BASELINE_SAMPLES", 30))


class PortHistory:
    def __init__(self, path: str | None = None):
        self.path = path or data_path(".history.json")
        self._samples: dict[str, list[dict]] = {}

    def load(self) -> None:
        self._samples = load_json(self.path, {})
        self._prune()

    def save(self) -> None:
        save_json(self.path, self._samples)

    def record(self, port_id: str, sample: dict) -> None:
        self._samples.setdefault(port_id, []).append({"ts": time.time(), **sample})
        self._prune()

    def samples(self, port_id: str, hours: float = 24) -> list[dict]:
        cutoff = time.time() - hours * 3600
        return [s for s in self._samples.get(port_id, []) if s["ts"] >= cutoff]

    def baseline(self, port_id: str) -> float | None:
        """The port's usual queue: median of everything recorded (up to 7 days).
        None until there are enough samples to be meaningful."""
        queues = [s["vessel_queue_length"] for s in self._samples.get(port_id, [])]
        if len(queues) < MIN_BASELINE_SAMPLES:
            return None
        return float(statistics.median(queues))

    def trend(self, port_id: str, points: int = 48) -> list[dict]:
        """Down-sampled queue/tier series for sparklines (at most `points` entries)."""
        samples = self.samples(port_id, hours=24)
        if len(samples) <= points:
            chosen = samples
        else:
            step = len(samples) / points
            chosen = [samples[int(i * step)] for i in range(points)]
            chosen[-1] = samples[-1]
        return [{"ts": s["ts"], "queue": s["vessel_queue_length"], "tier": s["tier"]} for s in chosen]

    def _prune(self) -> None:
        cutoff = time.time() - RETENTION_SECONDS
        for port_id, samples in self._samples.items():
            self._samples[port_id] = [s for s in samples if s["ts"] >= cutoff]


history = PortHistory()
