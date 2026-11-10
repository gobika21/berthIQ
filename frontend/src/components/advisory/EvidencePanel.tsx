"use client";

import { History, Scale } from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";
import { TierBadge } from "@/components/ui/TierBadge";
import { useLocale } from "@/components/LocaleProvider";
import { cn } from "@/lib/cn";
import { fill } from "@/lib/format";
import type { Evidence, MetricKey, Precedent } from "@/lib/types";

const METRIC_LABEL_KEYS: Record<MetricKey, string> = {
  berth_occupancy_rate: "howFullThePort",
  vessel_queue_length: "shipsWaiting",
  avg_waiting_time_hours: "averageDelay",
};

function formatMetric(metric: MetricKey, value: number): string {
  if (metric === "berth_occupancy_rate") return `${Math.round(value * 100)}%`;
  if (metric === "avg_waiting_time_hours") return `${value}h`;
  return String(value);
}

/** Shows exactly which numbers and thresholds produced the tier, and which past episodes were used. */
export function EvidencePanel({ evidence, precedents }: { evidence: Evidence; precedents: Precedent[] }) {
  const { t } = useLocale();
  const metrics = Object.keys(evidence.metrics) as MetricKey[];

  return (
    <Card>
      <CardBody className="flex flex-col gap-5">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <Scale className="h-4 w-4 text-accent" strokeWidth={2} />
          {t("whyThisTier")}
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {metrics.map((m) => {
            const th = evidence.thresholds[m];
            const driving = evidence.driving_metrics.includes(m);
            const tier = evidence.metric_tiers[m];
            return (
              <div
                key={m}
                className={cn(
                  "flex flex-col gap-2 rounded-sm border bg-sunken px-4 py-3",
                  driving ? "border-accent" : "border-border",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium uppercase tracking-wide text-ink-faint">{t(METRIC_LABEL_KEYS[m])}</span>
                  {driving && <span className="text-[10px] font-semibold uppercase text-accent">{t("mainDriver")}</span>}
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-lg font-semibold tabular-nums text-ink">{formatMetric(m, evidence.metrics[m])}</span>
                  {tier ? (
                    <TierBadge tier={tier} className="px-2 py-0.5 text-xs" />
                  ) : (
                    <span className="text-end text-[11px] leading-tight text-ink-faint">{t("notUsedForTier")}</span>
                  )}
                </div>
                {m === "vessel_queue_length" && (
                  <div className="text-[11px] text-ink-muted">
                    {evidence.queue_baseline != null
                      ? fill(t("comparedToUsual"), { n: Math.round(evidence.queue_baseline) })
                      : t("globalThresholds")}
                  </div>
                )}
                <div className="text-[11px] tabular-nums text-ink-faint" dir="ltr">
                  {t("thresholdsLabel")}: {t("tierLow")} &lt; {formatMetric(m, th.Low)} · {t("tierMedium")} &lt;{" "}
                  {formatMetric(m, th.Medium)} · {t("tierHigh")} &lt; {formatMetric(m, th.High)}
                </div>
              </div>
            );
          })}
        </div>

        {precedents.length > 0 && (
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-ink-muted">
              <History className="h-3.5 w-3.5" strokeWidth={2} />
              {t("similarPastEpisodes")}
            </div>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {precedents.map((p) => (
                <div key={p.id} className="rounded-sm border border-border bg-sunken px-4 py-3">
                  <div className="text-sm font-semibold text-ink">
                    {p.port_name} <span className="font-normal text-ink-faint">· {p.tier}</span>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-ink-muted">{p.summary}</p>
                  <p className="mt-2 text-xs leading-relaxed text-ink-faint">
                    <span className="font-medium text-ink-muted">{t("whatHelped")}: </span>
                    {p.outcome}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
