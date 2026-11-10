"""Single place where BerthIQ talks to Claude: client settings, timeouts and usage/cost tracking."""

import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar

from anthropic import Anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")

# Per-call timeout in seconds (the SDK default is 10 minutes, far too long for an
# interactive page). The SDK retries timeouts, connection errors, 429 and 5xx, so the
# worst case for one call is about TIMEOUT_S x (MAX_RETRIES + 1).
TIMEOUT_S = float(os.environ.get("CLAUDE_TIMEOUT_SECONDS", "30"))
MAX_RETRIES = int(os.environ.get("CLAUDE_MAX_RETRIES", "2"))

# List price in USD per million tokens for the model above (Claude Opus 4.5).
# Override with env vars if the model or pricing changes.
PRICE_INPUT_PER_MTOK = float(os.environ.get("CLAUDE_PRICE_INPUT_PER_MTOK", "5"))
PRICE_OUTPUT_PER_MTOK = float(os.environ.get("CLAUDE_PRICE_OUTPUT_PER_MTOK", "25"))

_client: Anthropic | None = None


def get_client() -> Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")
        _client = Anthropic(api_key=api_key, timeout=TIMEOUT_S, max_retries=MAX_RETRIES)
    return _client


# ---------------------------------------------------------------- usage tracking
class UsageTracker:
    """Adds up tokens across every Claude call made for one advisory (thread-safe:
    the three drafting calls run in parallel)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, usage) -> None:
        with self._lock:
            self.calls += 1
            self.input_tokens += getattr(usage, "input_tokens", 0) or 0
            self.output_tokens += getattr(usage, "output_tokens", 0) or 0

    def summary(self) -> dict:
        cost = (self.input_tokens * PRICE_INPUT_PER_MTOK + self.output_tokens * PRICE_OUTPUT_PER_MTOK) / 1_000_000
        return {
            "model": MODEL,
            "claude_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(cost, 5),
        }


_current: ContextVar[UsageTracker | None] = ContextVar("claude_usage", default=None)


@contextmanager
def track_usage():
    """Collect the usage of every ask_claude() call made inside this block.

    Worker threads must run in a copy of this context (see advisory_drafting) or
    their calls are not counted.
    """
    tracker = UsageTracker()
    token = _current.set(tracker)
    try:
        yield tracker
    finally:
        _current.reset(token)


def ask_claude(system: str, user: str, max_tokens: int = 1024) -> str:
    response = get_client().messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    tracker = _current.get()
    if tracker is not None:
        tracker.add(response.usage)
    return response.content[0].text
