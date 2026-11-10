"""Advisory-drafting agent: formats each recommendation into a persona-specific report."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

from app.claude_client import ask_claude
from app.models.schema import AdvisoryState

SYSTEM_PROMPT = """You draft short, clear advisory messages for port-logistics stakeholders. \
Given a persona, a recommended action, and the reasoning behind it, write a 2-4 sentence \
advisory message addressed directly to that stakeholder. Be concrete and actionable, and \
reference the underlying data point(s) that led to the recommendation. Plain text only, no \
markdown, no JSON.

Start directly with the advice: no heading, title, greeting, or "Advisory for ..." line — the \
interface already shows who the message is for. Never exceed 4 sentences.
"""

ARABIC_INSTRUCTION = "\n\nWrite the advisory message in Modern Standard Arabic."


def advisory_drafting_node(state: AdvisoryState) -> AdvisoryState:
    snapshot = state["snapshot"]
    language = state.get("language", "en")
    system_prompt = SYSTEM_PROMPT + (ARABIC_INSTRUCTION if language == "ar" else "")
    recommendations = state["recommendations"]

    def draft(rec: dict) -> str:
        user_prompt = (
            f"Port: {snapshot['port_name']}\n"
            f"Persona: {rec['persona']}\n"
            f"Recommended action: {rec['action']}\n"
            f"Reasoning: {rec['reasoning']}\n"
        )
        return ask_claude(system_prompt, user_prompt, max_tokens=300)

    # The three persona drafts are independent, so run them concurrently —
    # total latency becomes one Claude call instead of three back to back.
    # Each worker runs in its own copy of the caller's context so token usage
    # is still counted against this advisory (see claude_client.track_usage).
    contexts = [copy_context() for _ in recommendations]
    with ThreadPoolExecutor(max_workers=max(1, len(recommendations))) as pool:
        messages = list(pool.map(lambda ctx, rec: ctx.run(draft, rec), contexts, recommendations))

    return {"advisories": {rec["persona"]: msg for rec, msg in zip(recommendations, messages)}}
