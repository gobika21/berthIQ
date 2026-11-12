"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Info, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { MetricTile } from "@/components/ui/MetricTile";
import { NumberField } from "@/components/ui/NumberField";
import { Skeleton } from "@/components/ui/Skeleton";
import { TierBadge } from "@/components/ui/TierBadge";
import { LiveSignalPanel } from "@/components/board/LiveSignalPanel";
import { AdvisoryCard } from "./AdvisoryCard";
import { EvidencePanel } from "./EvidencePanel";
import { ImpactPanel } from "./ImpactPanel";
import { LoadingSteps } from "./LoadingSteps";
import { useLocale } from "@/components/LocaleProvider";
import { fallbackNoticeKey, keyWouldHelp, openAiKeyDialog } from "@/lib/aiKey";
import { api, ApiError } from "@/lib/api";
import { useLiveVesselQueue } from "@/lib/hooks";
import { TIER_STYLES } from "@/lib/tier";
import { fill } from "@/lib/format";
import type { AdvisoryResult, MetricKey, PortSnapshot } from "@/lib/types";

// Leaflet touches `window` at import time, so it can only run in the browser.
const ShipMap = dynamic(() => import("@/components/board/ShipMap").then((m) => m.ShipMap), {
  ssr: false,
  loading: () => <Skeleton className="h-[320px] w-full" />,
});

export function PortAdvisoryView({ portId }: { portId: string }) {
  const { data: live, loading: liveLoading, error: liveError } = useLiveVesselQueue(portId, true);
  const { locale, t } = useLocale();

  // The two fields follow the live reading until the person types their own figure.
  // "How full" is edited as a whole percent (0-100) — much clearer for a general
  // audience than a raw 0-1 fraction — and only converted to a fraction at submit time.
  const [fullPercent, setFullPercent] = useState(0);
  const [avgWaitHours, setAvgWaitHours] = useState(0);
  const [fullEdited, setFullEdited] = useState(false);
  const [waitEdited, setWaitEdited] = useState(false);
  const [result, setResult] = useState<AdvisoryResult | null>(null);
  // The exact numbers sent to the backend for `result` — kept separate from the live
  // inputs above so the results below can't silently drift out of sync with the live
  // feed polling in the background after the request was made.
  const [submittedSnapshot, setSubmittedSnapshot] = useState<PortSnapshot | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  // Screen-reader announcement for the ~20 s advisory run (start and finish).
  const [announcement, setAnnouncement] = useState("");
  // Bumped on every runAdvisoryFor call so a slow, now-stale request can't overwrite
  // the result of a newer one that resolved first (matters once language switches can
  // fire requests back-to-back).
  const requestIdRef = useRef(0);
  // Debounces the language-triggered refetch below, so toggling the language switch
  // rapidly issues one Claude call for the final choice instead of one per click.
  const localeDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const vesselQueueLength = live?.vessel_queue_length ?? 0;

  // A fetched result is written in whatever language was active at request time.
  // Rather than clearing it when the language changes, re-run the same snapshot
  // in the new language so the advisory text updates in place — the old text
  // stays on screen until the re-translated version arrives.
  const isFirstRender = useRef(true);
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    setRunError(null);
    if (!submittedSnapshot) return;

    if (localeDebounceRef.current) clearTimeout(localeDebounceRef.current);
    localeDebounceRef.current = setTimeout(() => {
      runAdvisoryFor({ ...submittedSnapshot, language: locale });
    }, 400);

    return () => {
      if (localeDebounceRef.current) clearTimeout(localeDebounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  // Live values: the same estimates the board uses when the port has a live level,
  // otherwise a rough starting point derived from the queue.
  const liveFullPercent =
    live?.berth_occupancy_rate != null
      ? Math.round(live.berth_occupancy_rate * 100)
      : Math.round(Math.min(95, 30 + vesselQueueLength * 4));
  const liveWaitHours = live?.avg_waiting_time_hours ?? Math.round(Math.min(48, vesselQueueLength * 1.2) * 2) / 2;
  const shownFullPercent = fullEdited ? fullPercent : liveFullPercent;
  const shownWaitHours = waitEdited ? avgWaitHours : Math.round(liveWaitHours * 10) / 10;

  async function runAdvisoryFor(snapshot: PortSnapshot) {
    const requestId = ++requestIdRef.current;
    setRunning(true);
    setRunError(null);
    setAnnouncement(t("srAdvisoryRunning"));
    try {
      const advisory = await api.runAdvisory(snapshot);
      if (requestId !== requestIdRef.current) return; // a newer request already resolved
      setResult(advisory);
      setSubmittedSnapshot(snapshot);
      setAnnouncement(fill(t("srAdvisoryReady"), { tier: t(TIER_STYLES[advisory.tier].labelKey) }));
    } catch (e) {
      if (requestId !== requestIdRef.current) return;
      setRunError(e instanceof ApiError ? e.message : t("somethingWentWrong"));
    } finally {
      if (requestId === requestIdRef.current) setRunning(false);
    }
  }

  function runAdvisory() {
    if (!live) return;
    // Rate it exactly like the live board: the queue (against this port's usual level)
    // and the delay. The fullness figure is only a guess, so it counts only when the
    // person entered their own.
    const tierMetrics: MetricKey[] = ["vessel_queue_length", "avg_waiting_time_hours"];
    if (fullEdited) tierMetrics.push("berth_occupancy_rate");
    runAdvisoryFor({
      port_name: live.port_name,
      berth_occupancy_rate: shownFullPercent / 100,
      vessel_queue_length: vesselQueueLength,
      avg_waiting_time_hours: waitEdited ? avgWaitHours : liveWaitHours,
      tier_metrics: tierMetrics,
      ...(live.queue_baseline != null ? { queue_baseline: live.queue_baseline } : {}),
      language: locale,
    });
  }

  if (liveLoading && !live) {
    return (
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Skeleton className="h-48 lg:col-span-1" />
        <Skeleton className="h-48 lg:col-span-2" />
      </div>
    );
  }

  if (liveError && !live) {
    return <ErrorBanner message={liveError} />;
  }

  if (!live) return null;

  return (
    <div className="flex flex-col gap-6">
      <p className="sr-only" role="status" aria-live="polite">
        {announcement}
      </p>
      <h2 className="text-lg font-semibold text-ink">{live.port_name}</h2>

      <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <LiveSignalPanel live={live}>{live.live_coverage && <ShipMap live={live} />}</LiveSignalPanel>
        </div>

        <Card className="flex flex-col lg:col-span-2">
          <CardBody className="flex flex-1 flex-col gap-4">
            <div className="text-sm font-medium text-ink">{t("fillInWhatYouKnow")}</div>
            <p className="text-xs leading-relaxed text-ink-faint">{t("fillInDescription")}</p>
            <div className="flex flex-col gap-3">
              <NumberField
                label={t("howFullThePort")}
                value={shownFullPercent}
                onChange={(v) => {
                  setFullPercent(Math.round(v));
                  setFullEdited(true);
                }}
                step={5}
                min={0}
                max={100}
                suffix="%"
              />
              <NumberField
                label={t("averageDelay")}
                value={shownWaitHours}
                onChange={(v) => {
                  setAvgWaitHours(Math.round(v * 2) / 2);
                  setWaitEdited(true);
                }}
                step={0.5}
                min={0}
                suffix="hrs"
              />
              {(fullEdited || waitEdited) && (
                <button
                  type="button"
                  onClick={() => {
                    setFullEdited(false);
                    setWaitEdited(false);
                  }}
                  className="self-start text-xs font-medium text-accent hover:text-accent-hover hover:underline"
                >
                  {t("resetToLive")}
                </button>
              )}
            </div>
            <div className="mt-auto pt-1">
              <Button onClick={runAdvisory} loading={running} className="w-full justify-center">
                <Sparkles className="h-3.5 w-3.5" />
                {t("getRecommendations")}
              </Button>
            </div>
          </CardBody>
        </Card>
      </div>

      {running && (
        <Card>
          <CardBody>
            <LoadingSteps />
          </CardBody>
        </Card>
      )}

      {runError && <ErrorBanner message={runError} />}

      {result && submittedSnapshot && (
        <div className="flex flex-col gap-6">
          <Card className={`border-s-4 ${TIER_STYLES[result.tier].border}`}>
            <CardBody className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <TierBadge tier={result.tier} />
                <p className="text-sm text-ink-muted">{result.tier_reasoning}</p>
              </div>
              <div className="grid grid-cols-1 gap-3 min-[420px]:grid-cols-3">
                <MetricTile
                  label={t("howFullThePort")}
                  value={`${Math.round(submittedSnapshot.berth_occupancy_rate * 100)}%`}
                  hint={
                    submittedSnapshot.tier_metrics && !submittedSnapshot.tier_metrics.includes("berth_occupancy_rate")
                      ? t("notUsedForTier")
                      : undefined
                  }
                />
                <MetricTile label={t("shipsWaiting")} value={submittedSnapshot.vessel_queue_length} />
                <MetricTile label={t("averageDelay")} value={`${submittedSnapshot.avg_waiting_time_hours}h`} />
              </div>
            </CardBody>
          </Card>

          <div>
            <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-ink-muted">
              {t("whatEachGroupShouldDo")}
            </div>
            {result.ai_status === "fallback" && (
            <div role="status"
              className="mb-3 flex items-start gap-2.5 rounded-sm border border-tier-medium/30 bg-tier-mediumSoft px-4 py-3 text-sm text-ink">
              <Info className="mt-0.5 h-4 w-4 flex-shrink-0" strokeWidth={1.75} aria-hidden="true" />
              <span>
                  {t(fallbackNoticeKey(result.ai_error))}
                  {keyWouldHelp(result.ai_error) && (
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
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              {result.recommendations.map((rec) => (
                <AdvisoryCard key={rec.persona} recommendation={rec} message={result.advisories[rec.persona]} />
              ))}
            </div>
          </div>

          {result.impact && <ImpactPanel impact={result.impact} />}
          {result.evidence && <EvidencePanel evidence={result.evidence} precedents={result.precedents ?? []} />}
        </div>
      )}
    </div>
  );
}
