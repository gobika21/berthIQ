"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BellOff, PlayCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { Skeleton } from "@/components/ui/Skeleton";
import { useLocale } from "@/components/LocaleProvider";
import { api, ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { useAlerts } from "@/lib/hooks";
import { fill } from "@/lib/format";
import type { AlertStatus } from "@/lib/types";
import { AlertCard } from "./AlertCard";

type Filter = "all" | AlertStatus;
const FILTERS: { key: Filter; labelKey: string }[] = [
  { key: "all", labelKey: "filterAll" },
  { key: "open", labelKey: "statusOpen" },
  { key: "acknowledged", labelKey: "statusAcknowledged" },
  { key: "resolved", labelKey: "statusResolved" },
];

export function AlertsCenter() {
  const { t } = useLocale();
  const { data: alerts, loading, error, refresh, replace } = useAlerts();
  const [filter, setFilter] = useState<Filter>("all");
  const [demoRunning, setDemoRunning] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  // Tell screen-reader users when the monitor raises new alerts (not on first load).
  const seenIds = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!alerts) return;
    const ids = new Set(alerts.map((a) => a.id));
    if (seenIds.current) {
      const fresh = alerts.filter((a) => !seenIds.current!.has(a.id)).length;
      if (fresh > 0) setAnnouncement(fill(t("srNewAlerts"), { n: fresh }));
    }
    seenIds.current = ids;
  }, [alerts, t]);

  // While the agents are drafting, check back every few seconds instead of every 10 s.
  const generating = alerts?.some((a) => a.advisory_status === "generating") ?? false;
  useEffect(() => {
    if (!generating) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [generating, refresh]);

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: 0, open: 0, acknowledged: 0, resolved: 0 };
    alerts?.forEach((a) => {
      c.all += 1;
      c[a.status] += 1;
    });
    return c;
  }, [alerts]);

  const visible = (alerts ?? []).filter((a) => filter === "all" || a.status === filter);

  async function runDemo() {
    setDemoRunning(true);
    setDemoError(null);
    try {
      await api.demoReplay();
      await refresh();
      setFilter("all");
    } catch (e) {
      setDemoError(e instanceof ApiError ? e.message : t("actionFailed"));
    } finally {
      setDemoRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "rounded-sm px-3 py-1.5 text-xs font-medium transition-colors",
              filter === f.key ? "bg-accent-soft text-accent-hover" : "text-ink-muted hover:bg-sunken hover:text-ink",
            )}
          >
            {t(f.labelKey)} <span className="tabular-nums">{counts[f.key]}</span>
          </button>
        ))}
        <Button variant="secondary" onClick={runDemo} loading={demoRunning} className="ms-auto">
          <PlayCircle className="h-3.5 w-3.5" />
          {t("runDemo")}
        </Button>
      </div>

      {demoError && <ErrorBanner message={demoError} />}
      {error && !alerts && <ErrorBanner message={error} />}

      {loading && !alerts ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : visible.length === 0 ? (
        <EmptyState icon={BellOff} title={t("noAlertsTitle")} description={t("noAlertsDescription")} />
      ) : (
        <div className="flex flex-col gap-4">
          {visible.map((a) => (
            <AlertCard key={a.id} alert={a} onChange={replace} onAnnounce={setAnnouncement} />
          ))}
        </div>
      )}
    </div>
  );
}
