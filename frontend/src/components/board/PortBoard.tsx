"use client";

import { Radio, Sailboat } from "lucide-react";
import { PortCard } from "./PortCard";
import { PortCardSkeleton } from "./PortCardSkeleton";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { EmptyState } from "@/components/ui/EmptyState";
import { useLocale } from "@/components/LocaleProvider";
import { useLiveVesselQueues } from "@/lib/hooks";
import { fill } from "@/lib/format";

export function PortBoard() {
  const { data: ports, loading, error } = useLiveVesselQueues();
  const { t } = useLocale();

  if (error && !ports) {
    return <ErrorBanner message={error} />;
  }

  if (loading && !ports) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <PortCardSkeleton key={i} />
        ))}
      </div>
    );
  }

  if (!ports || ports.length === 0) {
    return <EmptyState icon={Sailboat} title={t("noPortsTitle")} description={t("noPortsDescription")} />;
  }

  // One note for the whole board instead of repeating "Connecting" / "Trend builds…" on every card.
  const tracked = ports.filter((p) => p.live_coverage);
  const warming = tracked.filter((p) => p.warming_up).length;
  const trendsBuilding = tracked.some((p) => p.trend.length < 2);
  const note = warming > 0 ? fill(t("boardConnecting"), { n: warming }) : trendsBuilding ? t("boardTrendBuilding") : null;

  return (
    <div className="flex flex-col gap-4">
      {note && (
        <p
          role="status"
          className="flex items-center gap-2 self-start rounded-sm border border-border bg-surface px-3 py-2 text-xs text-ink-muted"
        >
          <Radio className={`h-3.5 w-3.5 flex-none ${warming > 0 ? "animate-pulse" : ""}`} strokeWidth={2} aria-hidden="true" />
          {note}
        </p>
      )}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {ports.map((port) => (
          <PortCard key={port.port_id} port={port} />
        ))}
      </div>
    </div>
  );
}
