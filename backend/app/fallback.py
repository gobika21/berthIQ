"""Rule-based advice used when Claude is unavailable (timeout, outage, unusable reply).

The congestion level, evidence and precedents never depend on Claude, so they stay
exactly the same; only the written recommendations fall back to fixed templates.
"""

from app.agents.decision_support import PERSONAS

SEVERE = {"High", "Critical"}

ACTIONS = {
    "en": {
        True: {
            "carrier": "Plan for delays: consider slowing the approach or re-sequencing port calls.",
            "trucking_company": "Confirm container release before dispatching drivers and move non-urgent pickups later.",
            "terminal_operator": "Prioritise berths for the longest-waiting ships and extend gate hours if possible.",
        },
        False: {
            "carrier": "Keep the current schedule and watch for changes.",
            "trucking_company": "Keep planned pickups and check release status before each dispatch.",
            "terminal_operator": "Run normal operations and keep berth plans under review.",
        },
    },
    "ar": {
        True: {
            "carrier": "استعدوا للتأخير: فكّروا في إبطاء الاقتراب من الميناء أو إعادة ترتيب مواعيد التوقف.",
            "trucking_company": "تأكدوا من الإفراج عن الحاويات قبل إرسال السائقين، وأجّلوا عمليات الاستلام غير العاجلة.",
            "terminal_operator": "امنحوا الأولوية في الأرصفة للسفن الأطول انتظارًا، ومدّدوا ساعات عمل البوابات إن أمكن.",
        },
        False: {
            "carrier": "حافظوا على الجدول الحالي وتابعوا أي تغييرات.",
            "trucking_company": "حافظوا على مواعيد الاستلام المخططة وتحققوا من حالة الإفراج قبل كل إرسال.",
            "terminal_operator": "استمروا في العمليات المعتادة مع مراجعة خطط الأرصفة.",
        },
    },
}

NOTE = {
    "en": "This is standard guidance for this congestion level; AI-written advice was unavailable.",
    "ar": "هذه إرشادات قياسية لهذا المستوى من الازدحام، إذ تعذّر الحصول على نصائح مكتوبة بالذكاء الاصطناعي.",
}


def _reasoning(snapshot: dict, tier: str, language: str) -> str:
    queue = snapshot["vessel_queue_length"]
    wait = f"{snapshot['avg_waiting_time_hours']:g}"
    baseline = snapshot.get("queue_baseline")
    if language == "ar":
        usual = f" (المعتاد نحو {round(baseline)})" if baseline is not None else ""
        return f"مستوى الازدحام {tier}: {queue} سفينة في الانتظار{usual}، ومتوسط الانتظار {wait} ساعة."
    usual = f" (usually about {round(baseline)})" if baseline is not None else ""
    return f"Congestion is {tier}: {queue} ships are waiting{usual} and the average wait is {wait} hours."


def fallback_advice(snapshot: dict, tier: str, language: str = "en") -> tuple[list[dict], dict]:
    """Return (recommendations, advisories) in the same shape the AI agents produce."""
    lang = language if language in ACTIONS else "en"
    actions = ACTIONS[lang][tier in SEVERE]
    reasoning = _reasoning(snapshot, tier, lang)
    recommendations = [
        {"persona": p, "action": actions[p], "reasoning": reasoning} for p in PERSONAS
    ]
    advisories = {p: f"{actions[p]} {reasoning} {NOTE[lang]}" for p in PERSONAS}
    return recommendations, advisories
