"""Classification agent: maps raw metrics to a Low/Medium/High/Critical tier."""

from app.models.schema import AdvisoryState
from app.thresholds import classify_metric, effective_thresholds

TIER_ORDER = ["Low", "Medium", "High", "Critical"]

TIER_SUMMARY = {
    "en": {
        "Low": "Traffic is light and ships are moving through quickly.",
        "Medium": "The port is busier than usual, with some delays starting to build.",
        "High": "The port is significantly congested — expect real delays.",
        "Critical": "The port is severely congested — expect major delays for anyone arriving now.",
    },
    "ar": {
        "Low": "الحركة في الميناء سلسة والسفن تتحرك بسرعة.",
        "Medium": "الميناء أكثر ازدحامًا من المعتاد، وبدأت بعض التأخيرات بالتراكم.",
        "High": "الميناء يشهد ازدحامًا كبيرًا — يُتوقع تأخير حقيقي.",
        "Critical": "الميناء يعاني من ازدحام شديد — يُتوقع تأخير كبير لأي سفينة تصل الآن.",
    },
}

REASONING_JOIN = {
    "en": "{summary} This is mainly because {facts}.",
    "ar": "{summary} ويعود ذلك أساسًا إلى أن {facts}.",
}


def _format_value(metric: str, value: float, language: str, baseline: float | None = None) -> str:
    usual = round(baseline) if baseline is not None else None
    if language == "ar":
        if metric == "berth_occupancy_rate":
            return f"الميناء ممتلئ بنسبة {round(value * 100)}%"
        if metric == "vessel_queue_length":
            return f"{int(value)} سفينة تنتظر" + (f" (المعتاد في هذا الميناء نحو {usual})" if usual is not None else "")
        return f"متوسط انتظار السفن {value} ساعة"

    if metric == "berth_occupancy_rate":
        return f"the port is {round(value * 100)}% full"
    if metric == "vessel_queue_length":
        count = int(value)
        text = f"{count} ship{'s' if count != 1 else ''} {'are' if count != 1 else 'is'} waiting"
        return text + (f" (usual for this port: about {usual})" if usual is not None else "")
    return f"ships are waiting an average of {value} hours"


def classification_node(state: AdvisoryState) -> AdvisoryState:
    result = classify_snapshot(state["snapshot"], state.get("language", "en"))
    return {
        "tier": result["tier"],
        "tier_reasoning": result["tier_reasoning"],
        "driving_metrics": result["driving_metrics"],
        "metric_tiers": result["metric_tiers"],
        "thresholds": result["thresholds"],
    }


ALL_METRICS = ("berth_occupancy_rate", "vessel_queue_length", "avg_waiting_time_hours")

# What the monitor can actually measure from AIS. Berth occupancy from AIS is only a
# rough estimate (every moored ship in the area ÷ a hand-sourced container-berth
# count), which saturates at 100% at big multi-purpose ports — so it's shown but
# kept out of automatic tiering.
LIVE_TIER_METRICS = ("vessel_queue_length", "avg_waiting_time_hours")


def classify_snapshot(snapshot: dict, language: str = "en") -> dict:
    """Pure, LLM-free tiering — also used by the background monitor on every tick.

    `snapshot["tier_metrics"]` (optional) limits which metrics count towards the tier.
    `snapshot["queue_baseline"]` (optional) is the port's usual queue; when present the
    queue is judged relative to it instead of against one global count.
    """
    used = tuple(snapshot.get("tier_metrics") or ALL_METRICS)
    baseline = snapshot.get("queue_baseline")
    thresholds = {m: effective_thresholds(m, baseline) for m in ALL_METRICS}
    metric_tiers = {m: classify_metric(snapshot[m], thresholds[m]) for m in ALL_METRICS if m in used}

    # Overall tier = the worst (highest) tier among the metrics in use
    overall_tier = max(metric_tiers.values(), key=TIER_ORDER.index)

    driving_metrics = [metric for metric, tier in metric_tiers.items() if tier == overall_tier]
    sep = "، " if language == "ar" else ", "
    driving_facts = sep.join(_format_value(m, snapshot[m], language, baseline) for m in driving_metrics)

    reasoning = REASONING_JOIN[language].format(summary=TIER_SUMMARY[language][overall_tier], facts=driving_facts)

    return {
        "tier": overall_tier,
        "tier_reasoning": reasoning,
        "driving_metrics": driving_metrics,
        "metric_tiers": metric_tiers,
        "thresholds": thresholds,
        "queue_baseline": baseline,
    }
