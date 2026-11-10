"""Detectors run by the monitor on every tick. Pure logic — no I/O — so they're easy to test.

Each detector returns zero or more alert specs (plain dicts); the monitor turns
them into stored alerts, applying cooldowns so the same event isn't re-raised.
Titles and messages come in English and Arabic.
"""

import os

TIER_ORDER = ["Low", "Medium", "High", "Critical"]
TIER_AR = {"Low": "منخفض", "Medium": "متوسط", "High": "مرتفع", "Critical": "حرج"}

# A new tier must be seen on this many consecutive ticks before it counts, so a
# single noisy reading (e.g. one ship briefly reporting "at anchor") can't fire an alert.
CONFIRM_TICKS = int(os.environ.get("MONITOR_CONFIRM_TICKS", 2))
# Escalations below this tier aren't worth interrupting anyone for.
MIN_ALERT_TIER = os.environ.get("MONITOR_MIN_ALERT_TIER", "Medium")

# An anchored ship swings around its anchor on the chain. With ~250 m of chain and a
# 300-400 m container ship, the AIS antenna can sit 600 m+ from the anchor, and the
# first "at anchor" fix (our reference point) can be anywhere on that circle. 500 m
# flagged ordinary swinging, so the line sits beyond a big ship's swing radius.
ANCHOR_DRAG_METERS = float(os.environ.get("ANCHOR_DRAG_METERS", 800))
# A dragging anchor moves a ship slowly, rarely above 2-3 knots. A ship doing 4-20 kn
# that still reports "at anchor" has weighed anchor and left without updating its AIS
# status. That's a data error, not a hazard: 20 of the first 24 live drag alerts were this.
ANCHOR_DRAG_MAX_KNOTS = float(os.environ.get("ANCHOR_DRAG_MAX_KNOTS", 3.0))
# Drift must stay past the line and keep growing for this many consecutive checks, so
# one bad GPS fix or a ship swinging out with the tide can't raise an alert on its own.
ANCHOR_DRAG_CONFIRM_TICKS = int(os.environ.get("ANCHOR_DRAG_CONFIRM_TICKS", 2))

GALE_GUST_KN = float(os.environ.get("WEATHER_GALE_GUST_KN", 34))  # Beaufort 8
FOG_VISIBILITY_M = float(os.environ.get("WEATHER_FOG_VISIBILITY_M", 1000))


def tier_index(tier: str) -> int:
    return TIER_ORDER.index(tier)


class TierTracker:
    """Tracks each port's confirmed tier and reports confirmed escalations."""

    def __init__(self, confirm_ticks: int = CONFIRM_TICKS):
        self.confirm_ticks = confirm_ticks
        self._confirmed: dict[str, str] = {}
        self._candidate: dict[str, tuple[str, int]] = {}

    def confirmed(self, port_id: str) -> str | None:
        return self._confirmed.get(port_id)

    def update(self, port_id: str, tier: str) -> tuple[str, str] | None:
        """Feed the latest tier. Returns (from_tier, to_tier) when an escalation is confirmed."""
        current = self._confirmed.get(port_id)
        if tier == current:
            self._candidate.pop(port_id, None)
            return None

        cand_tier, count = self._candidate.get(port_id, (tier, 0))
        count = count + 1 if cand_tier == tier else 1
        self._candidate[port_id] = (tier, count)
        if count < self.confirm_ticks:
            return None

        self._confirmed[port_id] = tier
        self._candidate.pop(port_id, None)
        baseline = current or "Low"  # first confirmation: only alert if it's already bad
        if tier_index(tier) > tier_index(baseline) and tier_index(tier) >= tier_index(MIN_ALERT_TIER):
            return baseline, tier
        return None


def escalation_alert(port_id: str, port_name: str, from_tier: str, to_tier: str, classification: dict,
                     snapshot: dict) -> dict:
    queue = snapshot["vessel_queue_length"]
    wait = snapshot["avg_waiting_time_hours"]
    baseline = classification.get("queue_baseline")
    return {
        "alert_type": "congestion_escalation",
        "severity": to_tier,
        "dedupe_key": f"escalation:{port_id}:{to_tier}",
        "title": {
            "en": f"{port_name}: congestion rose to {to_tier}",
            "ar": f"{port_name}: ارتفع مستوى الازدحام إلى {TIER_AR[to_tier]}",
        },
        "message": {
            "en": f"Congestion moved from {from_tier} to {to_tier}. {queue} ships are waiting at anchor"
                  + (f" (usual for this port: about {round(baseline)})" if baseline is not None else "")
                  + f", with an observed average wait of {wait} hours.",
            "ar": f"انتقل مستوى الازدحام من {TIER_AR[from_tier]} إلى {TIER_AR[to_tier]}. "
                  f"تنتظر {queue} سفينة في منطقة الرسو"
                  + (f" (المعتاد في هذا الميناء نحو {round(baseline)})" if baseline is not None else "")
                  + f"، بمتوسط انتظار ملاحَظ قدره {wait} ساعة.",
        },
        "evidence": {
            "from_tier": from_tier,
            "to_tier": to_tier,
            "metric_tiers": classification["metric_tiers"],
            "driving_metrics": classification["driving_metrics"],
            "queue_baseline": classification.get("queue_baseline"),
            "snapshot": {k: snapshot[k] for k in ("berth_occupancy_rate", "vessel_queue_length", "avg_waiting_time_hours")},
            "confirmed_after_ticks": CONFIRM_TICKS,
        },
    }


def drag_candidates(anchored: list[dict], threshold_m: float = ANCHOR_DRAG_METERS,
                    max_knots: float = ANCHOR_DRAG_MAX_KNOTS) -> list[dict]:
    """Ships that look like they're dragging on this one reading: past the swing radius,
    and slow enough to be dragging rather than sailing under a stale 'at anchor' status."""
    return [v for v in anchored if v["drift_m"] >= threshold_m and v["speed_knots"] <= max_knots]


class AnchorDragTracker:
    """Confirms drag over consecutive checks: the ship must stay past the line and keep
    moving further from its anchor point. A ship swinging on its chain doesn't."""

    def __init__(self, confirm_ticks: int = ANCHOR_DRAG_CONFIRM_TICKS):
        self.confirm_ticks = confirm_ticks
        self._streak: dict[tuple[str, str], tuple[int, int]] = {}  # (port, mmsi) -> (count, last drift)

    def update(self, port_id: str, candidates: list[dict]) -> list[dict]:
        """Feed this check's candidates for one port; returns those whose drag is confirmed."""
        seen = set()
        confirmed = []
        for v in candidates:
            key = (port_id, v["mmsi"])
            seen.add(key)
            count, last_drift = self._streak.get(key, (0, None))
            # The first sighting starts a streak; after that, drift has to keep growing.
            count = count + 1 if last_drift is None or v["drift_m"] > last_drift else 1
            self._streak[key] = (count, v["drift_m"])
            if count >= self.confirm_ticks:
                confirmed.append({**v, "confirmed_after_ticks": count})
        for key in [k for k in self._streak if k[0] == port_id and k not in seen]:
            del self._streak[key]  # back inside the line (or gone): start over next time
        return confirmed


def anchor_drag_alerts(port_id: str, port_name: str, anchored: list[dict],
                       threshold_m: float = ANCHOR_DRAG_METERS) -> list[dict]:
    """Alert specs for ships already judged to be dragging (see drag_candidates and
    AnchorDragTracker); the threshold only sets the severity and the message."""
    specs = []
    for v in anchored:
        if v["drift_m"] < threshold_m:
            continue
        severity = "Critical" if v["drift_m"] >= 2 * threshold_m else "High"
        specs.append({
            "alert_type": "anchor_drag",
            "severity": severity,
            "dedupe_key": f"anchor_drag:{port_id}:{v['mmsi']}",
            "title": {
                "en": f"{port_name}: possible anchor drag (MMSI {v['mmsi']})",
                "ar": f"{port_name}: احتمال انجراف مرساة (MMSI {v['mmsi']})",
            },
            "message": {
                "en": f"A ship reporting 'at anchor' is now {v['drift_m']} m from where it anchored "
                      f"(threshold {int(threshold_m)} m), moving at {v['speed_knots']} kn. Check the anchorage.",
                "ar": f"سفينة تُبلغ أنها راسية أصبحت على بُعد {v['drift_m']} م من موقع رسوّها "
                      f"(الحد {int(threshold_m)} م) وتتحرك بسرعة {v['speed_knots']} عقدة. يُرجى التحقق من منطقة الرسو.",
            },
            "evidence": {**v, "threshold_m": threshold_m},
        })
    return specs


def weather_alert(port_id: str, port_name: str, forecast: list[dict], tier: str | None) -> dict | None:
    """forecast: hourly [{'time', 'gust_kn', 'visibility_m'}] for the next ~12 hours."""
    if not forecast:
        return None
    gusts = [h for h in forecast if h.get("gust_kn") is not None]
    vis = [h for h in forecast if h.get("visibility_m") is not None]
    worst_gust = max(gusts, key=lambda h: h["gust_kn"]) if gusts else None
    worst_vis = min(vis, key=lambda h: h["visibility_m"]) if vis else None

    gale = worst_gust is not None and worst_gust["gust_kn"] >= GALE_GUST_KN
    fog = worst_vis is not None and worst_vis["visibility_m"] <= FOG_VISIBILITY_M
    if not (gale or fog):
        return None

    # Bad weather matters most where a queue already exists: pilotage and berthing
    # pauses turn an existing backlog into a much bigger one.
    busy = tier is not None and tier_index(tier) >= tier_index("Medium")
    severity = "High" if busy else "Medium"

    hazards_en, hazards_ar = [], []
    if gale:
        hazards_en.append(f"gusts up to {round(worst_gust['gust_kn'])} kn around {worst_gust['time'][11:16]}")
        hazards_ar.append(f"هبات رياح تصل إلى {round(worst_gust['gust_kn'])} عقدة نحو الساعة {worst_gust['time'][11:16]}")
    if fog:
        hazards_en.append(f"visibility down to {int(worst_vis['visibility_m'])} m around {worst_vis['time'][11:16]}")
        hazards_ar.append(f"انخفاض مدى الرؤية إلى {int(worst_vis['visibility_m'])} م نحو الساعة {worst_vis['time'][11:16]}")

    queue_note_en = " With a queue already building, expect pilotage or berthing pauses to lengthen delays." if busy else ""
    queue_note_ar = " ومع وجود طابور انتظار، قد يؤدي توقف الإرشاد أو الرسو إلى زيادة التأخير." if busy else ""

    return {
        "alert_type": "weather_risk",
        "severity": severity,
        "dedupe_key": f"weather:{port_id}",
        "title": {
            "en": f"{port_name}: weather risk in the next 12 hours",
            "ar": f"{port_name}: مخاطر جوية خلال الساعات الـ12 القادمة",
        },
        "message": {
            "en": "Forecast shows " + " and ".join(hazards_en) + " (UTC)." + queue_note_en,
            "ar": "تشير التوقعات إلى " + " و".join(hazards_ar) + " (بالتوقيت العالمي)." + queue_note_ar,
        },
        "evidence": {
            "gale": gale,
            "fog": fog,
            "worst_gust": worst_gust,
            "worst_visibility": worst_vis,
            "gale_threshold_kn": GALE_GUST_KN,
            "fog_threshold_m": FOG_VISIBILITY_M,
            "port_tier": tier,
            "source": "Open-Meteo forecast",
        },
    }
