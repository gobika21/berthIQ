"""State schema shared across the LangGraph agent pipeline."""

from typing import Literal, NotRequired, TypedDict

CongestionTier = Literal["Low", "Medium", "High", "Critical"]

Persona = Literal["carrier", "trucking_company", "terminal_operator"]

Language = Literal["en", "ar"]


class PortSnapshot(TypedDict):
    port_name: str
    berth_occupancy_rate: float  # 0-1
    vessel_queue_length: int  # number of vessels waiting
    avg_waiting_time_hours: float
    language: NotRequired[Language]
    situation: NotRequired[str]  # free-text context from an alert, e.g. a weather forecast
    tier_metrics: NotRequired[list[str]]  # metrics that count towards the tier (default: all three)
    queue_baseline: NotRequired[float]  # the port's usual queue; makes queue tiering port-relative


class Recommendation(TypedDict):
    persona: Persona
    action: str
    reasoning: str


class Precedent(TypedDict):
    id: str
    port_name: str
    tier: str
    summary: str
    outcome: str


class AdvisoryState(TypedDict, total=False):
    snapshot: PortSnapshot
    language: Language
    tier: CongestionTier
    tier_reasoning: str
    driving_metrics: list[str]
    metric_tiers: dict[str, CongestionTier]
    thresholds: dict[str, dict[str, float]]
    precedents: list[Precedent]
    recommendations: list[Recommendation]
    advisories: dict[Persona, str]
