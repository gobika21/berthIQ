"""Decision-support agent: Claude reasoning node producing per-persona recommendations."""

import json
import re

from app.claude_client import ask_claude
from app.models.schema import AdvisoryState

PERSONAS = ("carrier", "trucking_company", "terminal_operator")

SYSTEM_PROMPT = """You are a port operations decision-support analyst. Given a congestion \
snapshot, its tier, the reasoning behind that tier, and summaries of comparable past \
congestion episodes, produce concrete recommendations for three stakeholders: a carrier, \
a trucking company, and a terminal operator.

Cite the specific numbers that triggered each recommendation (e.g. "45 ships waiting" or \
"95% full"), but write for a general, non-technical reader. Do not use snake_case field \
names, code-style variable names, or jargon like "berth_occupancy_rate" anywhere in your \
output — always spell things out in plain English (e.g. say "the port is 95% full", never \
"berth_occupancy_rate=0.95"). Do not give a flat "safe/unsafe" verdict — explain the reasoning.

If a past episode below is genuinely relevant, you may reference what worked there (e.g. \
"during a similar backlog at another port, carriers that rebooked early avoided the worst \
delays"), but only if it's actually relevant — never force a comparison, never state it as \
fact for the current port, and never fabricate a precedent beyond what's given.

Respond ONLY with valid JSON, an array of exactly 3 objects, each shaped as:
{"persona": "carrier" | "trucking_company" | "terminal_operator", "action": "...", "reasoning": "..."}
"""

ARABIC_INSTRUCTION = (
    "\n\nWrite the \"action\" and \"reasoning\" text in Modern Standard Arabic. Keep the JSON "
    "keys and the \"persona\" values themselves in English exactly as specified above — only "
    "the text content is Arabic."
)


def decision_support_node(state: AdvisoryState) -> AdvisoryState:
    snapshot = state["snapshot"]
    tier = state["tier"]
    tier_reasoning = state["tier_reasoning"]
    precedents = state.get("precedents", [])
    language = state.get("language", "en")
    system_prompt = SYSTEM_PROMPT + (ARABIC_INSTRUCTION if language == "ar" else "")

    precedent_text = (
        "\n".join(
            f"- {p['port_name']} ({p['tier']}): {p['summary']} What helped: {p['outcome']}"
            for p in precedents
        )
        or "None found."
    )

    user_prompt = (
        f"Port: {snapshot['port_name']}\n"
        f"Congestion level: {tier}\n"
        f"Why: {tier_reasoning}\n"
        + (
            f"How full the port is: {round(snapshot['berth_occupancy_rate'] * 100)}%\n"
            if "berth_occupancy_rate" in (snapshot.get("tier_metrics") or ["berth_occupancy_rate"])
            # The live estimate saturates at big ports. Telling the model "don't rely on it" wasn't
            # enough (the exam set caught it quoting "99% capacity"), so the number isn't sent at all.
            else "How full the port is: not reliably measured from live ship tracking — do not quote "
                 "or estimate a percentage\n"
        )
        + f"Ships currently waiting: {snapshot['vessel_queue_length']}"
        + (f" (this port's usual level is about {round(snapshot['queue_baseline'])})"
           if snapshot.get("queue_baseline") is not None else "")
        + "\n"
        f"Average wait time: {snapshot['avg_waiting_time_hours']} hours\n\n"
        f"Comparable past episodes:\n{precedent_text}\n"
    )
    # Set by the monitor when advice is drafted for an alert (e.g. an incoming gale),
    # so recommendations address the actual event rather than the numbers alone.
    if snapshot.get("situation"):
        user_prompt += f"\nCurrent situation: {snapshot['situation']}\n"

    # One retry: if the model's reply doesn't parse or doesn't match the schema,
    # send the error back so it can correct itself instead of failing the request.
    raw = ask_claude(system_prompt, user_prompt)
    try:
        recommendations = _parse_recommendations(raw)
    except ValueError as exc:
        retry_prompt = (
            f"{user_prompt}\n\nYour previous reply was invalid ({exc}). "
            "Reply again with ONLY the JSON array described in your instructions."
        )
        recommendations = _parse_recommendations(ask_claude(system_prompt, retry_prompt))

    return {"recommendations": recommendations}


def _strip_code_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    # Tolerate prose around a bare array, e.g. "Here you go: [...]"
    start, end = text.find("["), text.rfind("]")
    return text[start : end + 1] if start != -1 and end > start else text


def _parse_recommendations(raw: str) -> list[dict]:
    """Parse and validate the model's reply; raises ValueError with a readable reason."""
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc.msg}") from exc

    if not isinstance(data, list):
        raise ValueError("expected a JSON array")

    by_persona: dict[str, dict] = {}
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each array item must be an object")
        persona = item.get("persona")
        action, reasoning = item.get("action"), item.get("reasoning")
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona!r}")
        if not isinstance(action, str) or not action.strip() or not isinstance(reasoning, str) or not reasoning.strip():
            raise ValueError(f"{persona} needs non-empty 'action' and 'reasoning' strings")
        by_persona[persona] = {"persona": persona, "action": action.strip(), "reasoning": reasoning.strip()}

    missing = [p for p in PERSONAS if p not in by_persona]
    if missing:
        raise ValueError(f"missing personas: {missing}")

    # Stable order (carrier, trucking, terminal) regardless of how the model ordered them
    return [by_persona[p] for p in PERSONAS]
