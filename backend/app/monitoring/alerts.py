"""Alert store and human-in-the-loop workflow.

Lifecycle of an alert:
    open → acknowledged → resolved

Lifecycle of the AI advisory attached to an alert:
    none → generating → pending_approval → approved | rejected
                      ↘ failed

Nothing an AI drafts is treated as "shared" until a person approves it.
"""

import threading
import time
import uuid

from app.monitoring.storage import data_path, load_json, save_json

ALERT_TYPES = ("congestion_escalation", "anchor_drag", "weather_risk")
ALERT_STATUSES = ("open", "acknowledged", "resolved")
ADVISORY_STATUSES = ("none", "generating", "pending_approval", "approved", "rejected", "failed")

MAX_ALERTS = 300


class AlertError(ValueError):
    """An action that isn't valid for the alert's current state."""


class AlertStore:
    def __init__(self, path: str | None = None):
        self.path = path or data_path(".alerts.json")
        self._alerts: list[dict] = []
        self._lock = threading.Lock()  # advisories are written from worker threads

    # ---------------------------------------------------------------- persistence
    def load(self) -> None:
        with self._lock:
            self._alerts = load_json(self.path, [])
            # An advisory that was mid-generation when the server stopped never finished.
            for a in self._alerts:
                if a.get("advisory_status") == "generating":
                    a["advisory_status"] = "failed"
                    a["advisory_error"] = "Server restarted while generating"

    def save(self) -> None:
        with self._lock:
            save_json(self.path, self._alerts)

    # ---------------------------------------------------------------- queries
    def list(self, status: str | None = None, port_id: str | None = None) -> list[dict]:
        with self._lock:
            items = [
                a for a in self._alerts
                if (status is None or a["status"] == status) and (port_id is None or a["port_id"] == port_id)
            ]
        return sorted(items, key=lambda a: a["created_at"], reverse=True)

    def get(self, alert_id: str) -> dict:
        with self._lock:
            for a in self._alerts:
                if a["id"] == alert_id:
                    return a
        raise KeyError(alert_id)

    def recent_exists(self, dedupe_key: str, within_seconds: float) -> bool:
        cutoff = time.time() - within_seconds
        with self._lock:
            return any(a["dedupe_key"] == dedupe_key and a["created_at"] >= cutoff for a in self._alerts)

    # ---------------------------------------------------------------- mutations
    def create(
        self,
        *,
        alert_type: str,
        port_id: str,
        port_name: str,
        severity: str,
        title: str,
        message: str,
        evidence: dict,
        dedupe_key: str,
        snapshot: dict | None = None,
        demo: bool = False,
    ) -> dict:
        assert alert_type in ALERT_TYPES, alert_type
        alert = {
            "id": uuid.uuid4().hex[:12],
            "type": alert_type,
            "port_id": port_id,
            "port_name": port_name,
            "severity": severity,
            "title": title,
            "message": message,
            "evidence": evidence,
            "snapshot": snapshot,
            "dedupe_key": dedupe_key,
            "demo": demo,
            "created_at": time.time(),
            "status": "open",
            "advisory_status": "none",
            "advisory": None,
            "advisory_error": None,
            "log": [{"at": time.time(), "action": "created", "by": "monitor", "note": None}],
        }
        with self._lock:
            self._alerts.append(alert)
            if len(self._alerts) > MAX_ALERTS:
                self._alerts = self._alerts[-MAX_ALERTS:]
        self.save()
        return alert

    def _log(self, alert: dict, action: str, by: str, note: str | None) -> None:
        alert["log"].append({"at": time.time(), "action": action, "by": by, "note": note})

    def acknowledge(self, alert_id: str, by: str = "operator", note: str | None = None) -> dict:
        alert = self.get(alert_id)
        if alert["status"] != "open":
            raise AlertError(f"Only open alerts can be acknowledged (this one is {alert['status']})")
        alert["status"] = "acknowledged"
        self._log(alert, "acknowledged", by, note)
        self.save()
        return alert

    def resolve(self, alert_id: str, by: str = "operator", note: str | None = None) -> dict:
        alert = self.get(alert_id)
        if alert["status"] == "resolved":
            raise AlertError("Alert is already resolved")
        if alert["advisory_status"] == "pending_approval":
            raise AlertError("Approve or reject the AI advisory before resolving")
        alert["status"] = "resolved"
        self._log(alert, "resolved", by, note)
        self.save()
        return alert

    def review_advisory(self, alert_id: str, approve: bool, by: str = "operator", note: str | None = None) -> dict:
        alert = self.get(alert_id)
        if alert["advisory_status"] != "pending_approval":
            raise AlertError(f"No advisory awaiting approval (status: {alert['advisory_status']})")
        alert["advisory_status"] = "approved" if approve else "rejected"
        if alert["status"] == "open":
            alert["status"] = "acknowledged"  # reviewing implies a human has seen it
        self._log(alert, "advisory_approved" if approve else "advisory_rejected", by, note)
        self.save()
        return alert

    def mark_generating(self, alert_id: str) -> dict:
        alert = self.get(alert_id)
        if alert["advisory_status"] in ("generating", "pending_approval", "approved"):
            raise AlertError(f"Advisory already {alert['advisory_status']}")
        if not alert.get("snapshot"):
            raise AlertError("This alert type has no port snapshot to advise on")
        alert["advisory_status"] = "generating"
        alert["advisory_error"] = None
        self._log(alert, "advisory_requested", "monitor", None)
        self.save()
        return alert

    def set_advisory(self, alert_id: str, advisory: dict | None, error: str | None = None) -> dict:
        alert = self.get(alert_id)
        if error:
            alert["advisory_status"] = "failed"
            alert["advisory_error"] = error
            self._log(alert, "advisory_failed", "agents", error)
        else:
            alert["advisory"] = advisory
            alert["advisory_status"] = "pending_approval"
            self._log(alert, "advisory_drafted", "agents", None)
        self.save()
        return alert


alerts = AlertStore()
