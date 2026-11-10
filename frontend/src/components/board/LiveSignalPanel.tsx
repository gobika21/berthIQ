"use client";

import { Radio, RadioTower } from "lucide-react";
import { Card, CardBody } from "@/components/ui/Card";
import { MetricTile } from "@/components/ui/MetricTile";
import { Sparkline } from "@/components/ui/Sparkline";
import { TierBadge } from "@/components/ui/TierBadge";
import { describeTrend } from "@/lib/format";
import { useLocale } from "@/components/LocaleProvider";
import type { LiveVesselQueue } from "@/lib/types";

export function LiveSignalPanel({ live, children }: { live: LiveVesselQueue; children?: React.ReactNode }) {
  const { t } = useLocale();
  const hasSignal = live.live_coverage && !live.warming_up;

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardBody className="flex flex-1 flex-col gap-4">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          {live.live_coverage ? (
            <Radio className={hasSignal ? "h-4 w-4 text-tier-low" : "h-4 w-4 text-ink-faint"} strokeWidth={2} />
          ) : (
            <RadioTower className="h-4 w-4 text-ink-faint" strokeWidth={2} />
          )}
          {t("liveShipTracking")}
          {live.tier && <TierBadge tier={live.tier} className="ms-auto px-2 py-0.5 text-xs" />}
        </div>
        <p className="text-xs leading-relaxed text-ink-faint">{live.coverage_note}</p>
        <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
          <MetricTile label={t("shipsNearby")} value={live.vessels_observed} />
          <MetricTile label={t("shipsWaiting")} value={live.vessel_queue_length} hint={t("usedBelow")} />
          <MetricTile label={t("shipsAtBerth")} value={live.vessels_at_berth} />
        </div>
        {live.warming_up && live.live_coverage && (
          <p className="text-xs text-ink-faint">{t("warmingUp")}</p>
        )}
        {live.live_coverage && (
          <div className="flex items-center justify-between gap-3">
            <span className="text-[11px] uppercase tracking-wide text-ink-faint">{t("last24h")}</span>
            {live.trend.length >= 2 ? (
              <Sparkline points={live.trend} width={260} height={36} label={describeTrend(live.trend, t("trendSummary"))} />
            ) : (
              <span className="text-xs text-ink-faint">{t("trendBuilding")}</span>
            )}
          </div>
        )}
      </CardBody>
      {children && <div className="border-t border-border">{children}</div>}
    </Card>
  );
}
