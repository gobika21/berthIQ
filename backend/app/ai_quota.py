"""The server's free daily allowance of AI runs, shared by visitors and the monitor.

Each run is one advisory (about four Claude calls) paid by the server's
ANTHROPIC_API_KEY. Visitors who bring their own key are not counted. In memory:
it resets at midnight UTC and on restart, which is fine for a single-instance demo.
"""

import os
import threading
from datetime import datetime, timezone

FREE_AI_RUNS_PER_DAY = int(os.environ.get("FREE_AI_RUNS_PER_DAY", 10))

_lock = threading.Lock()
_state = {"day": "", "used": 0}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def server_key_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY")) and FREE_AI_RUNS_PER_DAY > 0


def free_runs_left() -> int:
    if not server_key_available():
        return 0
    with _lock:
        used = _state["used"] if _state["day"] == _today() else 0
    return max(0, FREE_AI_RUNS_PER_DAY - used)


def claim_free_run() -> bool:
    """Take one run from today's allowance; False when none is left or there is no server key."""
    if not server_key_available():
        return False
    with _lock:
        if _state["day"] != _today():
            _state.update(day=_today(), used=0)
        if _state["used"] >= FREE_AI_RUNS_PER_DAY:
            return False
        _state["used"] += 1
        return True


def reset_for_tests() -> None:
    with _lock:
        _state.update(day="", used=0)
