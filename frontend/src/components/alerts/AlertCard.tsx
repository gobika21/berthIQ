"use client";

import { useState } from "react";
import { Anchor, Check, ChevronDown, CloudLightning, Info, Loader2, Ship, Sparkles, TrendingUp, Truck, Warehouse, X } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { TierBadge } from "@/components/ui/TierBadge";
import { useLocale } from "@/components/LocaleProvider";
import { fallbackNoticeKey, keyWouldHelp, openAiKeyDialog } from "@/lib/aiKey";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { fill, formatNumber, formatUsd, timeAgo } from "@/lib/format";
import { PERSONA_LABEL_KEYS, TIER_STYLES } from "@/lib/tier";
import type { Alert, AlertStatus, AlertType, Persona } from "@/lib/types";

const TYPE_META: Record<AlertType, { icon: typeof Anchor; labelKey: string }> = {
  congestion_escalation: { icon: TrendingUp, labelKey: "alertTypeEscalation" },
  anchor_drag: { icon: Anchor, labelKey: "alertTypeAnchor" },
  weather_risk: { icon: CloudLightning, labelKey: "alertTypeWeather" },
};

const STATUS_KEYS: Record<AlertStatus, string> = {
  open: "statusOpen",
  acknowledged: "statusAcknowledged",
  resolved: "statusResolved",
};

const PERSONA_ICONS: Record<Persona, typeof Ship> = {
  carrier: Ship,
  trucking_company: Truck,
  terminal_operator: Warehouse,
};

type Action = "acknowledge" | "approve" | "reject" | "resolve" | "advise";

function EvidenceList({ evidence, label }: { evidence: Record<string, unknown>; label: (key: string) => string }) {
  const rows = Object.entries(evidence).filter(([, v]) => v !== null && typeof v !== "object");
  if (rows.length === 0) return null;
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
      {rows.map(([k, v]) => (
        <div key={k} className="flex justify-between gap-3 border-b border-border py-1">
          <dt className="text-ink-faint">{label(`ev_${k}`)}</dt>
          <dd className="tabular-nums text-ink-muted" dir="ltr">
            {String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

const ACTION_DONE_KEYS: Record<Action, string> = {
  acknowledge: "srAcknowledged",
  approve: "srApproved",
  reject: "srRejected",
  resolve: "srResolved",
  advise: "srAdviceRequested",
};

export function AlertCard({
  alert,
  onChange,
  onAnnounce,
}: {
  alert: Alert;
  onChange: (a: Alert) => void;
  onAnnounce?: (message: string) => void;
}) {
  const { locale, t } = useLocale();
  const [busy, setBusy] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showEvidence, setShowEvidence] = useState(false);
  const [showLog, setShowLog] = useState(false);

  // Translated label for a dynamic key, falling back to a readable version of the key.
  const label = (key: string) => {
    const text = t(key);
    return text === key ? key.replace(/^[a-z]+_/, "").replace(/_/g, " ") : text;
  };
  const meta = TYPE_META[alert.type];
  const Icon = meta.icon;
  const advisory = alert.advisory;

  async function act(action: Action) {
    setBusy(action);
    setError(null);
    try {
      const updated = action === "advise" ? await api.requestAlertAdvisory(alert.id) : await api.alertAction(alert.id, action);
      onChange(updated);
      onAnnounce?.(t(ACTION_DONE_KEYS[action]));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("actionFailed"));
    } finally {
      setBusy(null);
    }
  }

  const canAdvise = alert.snapshot !== null && ["none", "failed", "rejected"].includes(alert.advisory_status);

  return (
    <Card className={cn("border-s-4", TIER_STYLES[alert.severity].border)}>
      <CardBody className="flex flex-col gap-4">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-accent-soft text-accent-hover">
            <Icon className="h-4 w-4" strokeWidth={1.75} />
          </div>
          <span className="text-xs font-semibold uppercase tracking-wide text-ink-muted">{t(meta.labelKey)}</span>
          <TierBadge tier={alert.severity} className="px-2 py-0.5 text-xs" />
          {alert.demo && <Badge tone="warning">{t("demoBadge")}</Badge>}
          <Badge tone={alert.status === "open" ? "accent" : "neutral"}>{t(STATUS_KEYS[alert.status])}</Badge>
          <span className="ms-auto text-xs text-ink-faint">{timeAgo(alert.created_at, locale)}</span>
        </div>

        <div>
          <div className="text-[15px] font-semibold text-ink">{alert.title[locale] ?? alert.title.en}</div>
          <p className="mt-1 text-sm leading-relaxed text-ink-muted">{alert.message[locale] ?? alert.message.en}</p>
        </div>

        {/* AI advisory */}
        {alert.advisory_status === "generating" && (
          <div className="flex items-center gap-2 rounded-sm border border-border bg-sunken px-4 py-3 text-sm text-ink-muted">
            <Loader2 className="h-4 w-4 motion-safe:animate-spin text-accent" />
            {t("advisoryGenerating")}
          </div>
        )}

        {advisory && ["pending_approval", "approved", "rejected", "expired"].includes(alert.advisory_status) && (
          <div
            className={cn(
              "flex flex-col gap-3 rounded-sm border px-4 py-3",
              alert.advisory_status === "pending_approval" && "border-accent bg-accent-soft",
              alert.advisory_status === "approved" && "border-tier-low/40 bg-tier-lowSoft",
              (alert.advisory_status === "rejected" || alert.advisory_status === "expired") && "border-border bg-sunken",
            )}
          >
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink">
              <Sparkles className="h-3.5 w-3.5" />
              {t(
                alert.advisory_status === "pending_approval"
                  ? "advisoryPending"
                  : alert.advisory_status === "approved"
                    ? "advisoryApproved"
                    : alert.advisory_status === "expired"
                      ? "advisoryExpired"
                      : "advisoryRejected",
              )}
            </div>
            {advisory.ai_status === "fallback" && (
              <div role="status"
                className="flex items-start gap-2.5 rounded-sm border border-tier-medium/30 bg-tier-mediumSoft px-4 py-3 text-sm text-ink">
                <Info className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
                <span>
                  {t(fallbackNoticeKey(advisory.ai_error))}
                  {keyWouldHelp(advisory.ai_error) && (
                    <>
                      {" "}
                      <button type="button" onClick={openAiKeyDialog} className="font-medium text-accent hover:underline">
                        {t("aiAddKeyCta")}
                      </button>
                    </>
                  )}
                </span>
              </div>
            )}
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              {advisory.recommendations.map((rec) => {
                const PIcon = PERSONA_ICONS[rec.persona];
                return (
                  <div key={rec.persona} className="flex flex-col gap-1.5">
                    <div className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                      <PIcon className="h-3.5 w-3.5" strokeWidth={1.75} />
                      {t(PERSONA_LABEL_KEYS[rec.persona])}
                    </div>
                    <p className="text-xs leading-relaxed text-ink-muted">{advisory.advisories[rec.persona]}</p>
                  </div>
                );
              })}
            </div>
            {advisory.impact && advisory.impact.jit_per_ship.fuel_saved_t > 0 && (
              <div className="text-xs text-ink-muted">
                {t("jitTitle")}:{" "}
                {fill(t("slowFromTo"), {
                  from: advisory.impact.jit_per_ship.service_speed_kn,
                  to: advisory.impact.jit_per_ship.recommended_speed_kn,
                })}{" "}
                — {formatNumber(advisory.impact.jit_per_ship.fuel_saved_t, locale)} t {t("fuelSaved").toLowerCase()},{" "}
                ≈ {formatUsd(advisory.impact.jit_per_ship.cost_saved_usd, locale)} ({t("estimate").toLowerCase()})
              </div>
            )}
            {alert.advisory_status === "pending_approval" && (
              <div className="flex flex-wrap gap-2">
                <Button onClick={() => act("approve")} loading={busy === "approve"} disabled={busy !== null}>
                  <Check className="h-3.5 w-3.5" />
                  {t("approve")}
                </Button>
                <Button variant="secondary" onClick={() => act("reject")} loading={busy === "reject"} disabled={busy !== null}>
                  <X className="h-3.5 w-3.5" />
                  {t("reject")}
                </Button>
              </div>
            )}
          </div>
        )}

        {alert.advisory_status === "failed" && (
          <p className="text-xs text-tier-criticalText">
            {t("advisoryFailed")}
            {alert.advisory_error ? ` — ${alert.advisory_error}` : ""}
          </p>
        )}

        {error && <p role="alert" className="text-xs text-tier-criticalText">{error}</p>}

        {/* Workflow actions */}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          {canAdvise && (
            <Button variant="secondary" onClick={() => act("advise")} loading={busy === "advise"} disabled={busy !== null}>
              <Sparkles className="h-3.5 w-3.5" />
              {alert.advisory_status === "none" ? t("generateAdvice") : t("retryAdvice")}
            </Button>
          )}
          {alert.status === "open" && (
            <Button variant="ghost" onClick={() => act("acknowledge")} loading={busy === "acknowledge"} disabled={busy !== null}>
              {t("acknowledge")}
            </Button>
          )}
          {alert.status !== "resolved" && alert.advisory_status !== "pending_approval" && alert.advisory_status !== "generating" && (
            <Button variant="ghost" onClick={() => act("resolve")} loading={busy === "resolve"} disabled={busy !== null}>
              {t("resolve")}
            </Button>
          )}
          <div className="ms-auto flex gap-3">
            <button
              type="button"
              onClick={() => setShowEvidence((v) => !v)}
              aria-expanded={showEvidence}
              className="flex items-center gap-1 text-xs font-medium text-ink-faint hover:text-ink-muted"
            >
              {t("evidence")}
              <ChevronDown className={cn("h-3 w-3 transition-transform", showEvidence && "rotate-180")} />
            </button>
            <button
              type="button"
              onClick={() => setShowLog((v) => !v)}
              aria-expanded={showLog}
              className="flex items-center gap-1 text-xs font-medium text-ink-faint hover:text-ink-muted"
            >
              {t("activity")}
              <ChevronDown className={cn("h-3 w-3 transition-transform", showLog && "rotate-180")} />
            </button>
          </div>
        </div>

        {showEvidence && <EvidenceList evidence={alert.evidence} label={label} />}
        {showLog && (
          <ol className="flex flex-col gap-1 text-xs text-ink-faint">
            {alert.log.map((entry, i) => (
              <li key={i} className="flex justify-between gap-3">
                <span>
                  <span className="text-ink-muted">{label(`log_${entry.action}`)}</span> · {label(`by_${entry.by}`)}
                  {entry.note ? ` — ${entry.note}` : ""}
                </span>
                <span>{timeAgo(entry.at, locale)}</span>
              </li>
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}
