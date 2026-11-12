"use client";

import Link from "next/link";
import { ArrowRight, Radio, RadioTower } from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Sparkline } from "@/components/ui/Sparkline";
import { TierBadge } from "@/components/ui/TierBadge";
import { useLocale } from "@/components/LocaleProvider";
import { describeTrend, fill, formatUsd } from "@/lib/format";
import { TIER_STYLES } from "@/lib/tier";
import { cn } from "@/lib/cn";
import type { LiveVesselQueue } from "@/lib/types";

export function PortCard({ port }: { port: LiveVesselQueue }) {
  const { locale, t } = useLocale();
  const hasSignal = port.live_coverage && port.connected && !port.warming_up;
  const hasTrend = port.trend.length >= 2;
  const hasIdleCost = port.idle_cost_usd !== null && port.idle_cost_usd > 0;
  const tierLabel = port.tier ? t(TIER_STYLES[port.tier].labelKey) : t("tierUnknown");
  const summary = port.live_coverage
    ? fill(t("portCardSummary"), {
        port: port.port_name,
        country: port.country,
        tier: tierLabel,
        n: port.vessel_queue_length,
        usual: port.queue_baseline != null ? fill(t("usualQueue"), { n: Math.round(port.queue_baseline) }) : "",
      })
    : fill(t("portCardSummaryNoData"), { port: port.port_name, country: port.country });

  return (
    <Link href={`/port/${port.port_id}`} className="group block" aria-label={summary}>
      <Card
        className={cn(
          "transition-shadow group-hover:shadow-raised",
          port.tier && `border-s-4 ${TIER_STYLES[port.tier].border}`,
        )}
      >
        <CardBody className="flex flex-col gap-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[15px] font-semibold text-ink">{port.port_name}</div>
              <div className="text-xs text-ink-faint">{port.country}</div>
            </div>
            {/* While connecting or offline, the board shows one shared note instead of a badge per card. */}
            {port.live_coverage ? (
              hasSignal && (
                <Badge tone="success">
                  <Radio className="h-3 w-3" strokeWidth={2} />
                  {t("live")}
                </Badge>
              )
            ) : (
              <Badge tone="neutral">
                <RadioTower className="h-3 w-3" strokeWidth={2} />
                {t("noLiveData")}
              </Badge>
            )}
          </div>

          <div className="flex items-end justify-between gap-3">
            <div>
              <div className="text-2xl font-semibold tabular-nums text-ink">{port.vessel_queue_length}</div>
              <div className="text-xs text-ink-faint">
                {t("shipsWaitingRightNow")}
                {port.queue_baseline != null && (
                  <span> · {fill(t("usualQueue"), { n: Math.round(port.queue_baseline) })}</span>
                )}
              </div>
            </div>
            {port.tier ? (
              <TierBadge tier={port.tier} className="text-xs" />
            ) : (
              hasSignal && <span className="text-xs text-ink-faint">{t("tierUnknown")}</span>
            )}
          </div>

          {/* Trend row only once there is something to show; the board explains the wait once. */}
          {port.live_coverage && (hasTrend || hasIdleCost) && (
            <div className="flex items-end justify-between gap-3 border-t border-border pt-3">
              <div className="min-w-0">
                <div className="text-[11px] uppercase tracking-wide text-ink-faint">{t("last24h")}</div>
                {hasTrend ? (
                  <Sparkline points={port.trend} label={describeTrend(port.trend, t("trendSummary"))} className="mt-1" />
                ) : (
                  <div className="mt-1 text-xs text-ink-faint">{t("trendBuilding")}</div>
                )}
              </div>
              {hasIdleCost && (
                <div className="text-end">
                  <div className="text-[11px] uppercase tracking-wide text-ink-faint">{t("idleCostLabel")}</div>
                  <div className="text-sm font-semibold tabular-nums text-ink">{formatUsd(port.idle_cost_usd ?? 0, locale)}</div>
                </div>
              )}
            </div>
          )}

          <span className="flex items-center gap-1 text-xs font-medium text-accent opacity-0 transition-opacity group-hover:opacity-100">
            {t("seeRecommendations")}
            <ArrowRight className="h-3.5 w-3.5 rtl:rotate-180" />
          </span>
        </CardBody>
      </Card>
    </Link>
  );
}
