"use client";

import { useState } from "react";
import { ChevronDown, Fuel, Gauge, Leaf, Timer, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody } from "@/components/ui/Card";
import { useLocale } from "@/components/LocaleProvider";
import { cn } from "@/lib/cn";
import { fill, formatNumber, formatUsd } from "@/lib/format";
import type { Impact } from "@/lib/types";

function Stat({ icon: Icon, label, value }: { icon: typeof Fuel; label: string; value: string }) {
  return (
    <div className="rounded-sm border border-border bg-sunken px-4 py-3">
      <div className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-ink-faint">
        <Icon className="h-3.5 w-3.5" strokeWidth={2} />
        {label}
      </div>
      <div className="mt-1 text-xl font-semibold tabular-nums text-ink">{value}</div>
    </div>
  );
}

/** "What it's worth": idle ship time now, and the saving if one inbound ship arrives just in time. */
export function ImpactPanel({ impact }: { impact: Impact }) {
  const { locale, t } = useLocale();
  const [showAssumptions, setShowAssumptions] = useState(false);
  const jit = impact.jit_per_ship;
  const hasSaving = jit.fuel_saved_t > 0;

  return (
    <Card>
      <CardBody className="flex flex-col gap-4">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <Wallet className="h-4 w-4 text-accent" strokeWidth={2} />
          {t("impactTitle")}
          <Badge tone="warning">{t("estimate")}</Badge>
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <Stat
            icon={Timer}
            label={t("idleTimeNow")}
            value={`${formatNumber(impact.idle.idle_ship_hours, locale, 0)} ${t("shipHours")}`}
          />
          <Stat icon={Wallet} label={t("idleCostLabel")} value={formatUsd(impact.idle.idle_cost_usd, locale)} />
          <Stat icon={Fuel} label={t("fuelSaved")} value={`${formatNumber(jit.fuel_saved_t, locale)} t`} />
          <Stat icon={Leaf} label={t("co2Saved")} value={`${formatNumber(jit.co2_saved_t, locale)} t`} />
        </div>

        {hasSaving && (
          <div className="flex flex-wrap items-center gap-2 rounded-sm border border-tier-low/30 bg-tier-lowSoft px-4 py-3 text-sm text-ink">
            <Gauge className="h-4 w-4 text-tier-low" strokeWidth={2} />
            <span className="font-medium">{t("jitTitle")}:</span>
            <span>{fill(t("slowFromTo"), { from: jit.service_speed_kn, to: jit.recommended_speed_kn })}</span>
            <span className="font-semibold text-tier-low">≈ {formatUsd(jit.cost_saved_usd, locale)}</span>
          </div>
        )}

        <button
          type="button"
          onClick={() => setShowAssumptions((v) => !v)}
          aria-expanded={showAssumptions}
          className="flex items-center gap-1 self-start text-xs font-medium text-ink-faint hover:text-ink-muted"
        >
          {t("assumptions")}
          <ChevronDown className={cn("h-3 w-3 transition-transform", showAssumptions && "rotate-180")} />
        </button>
        {showAssumptions && (
          <div className="flex flex-col gap-2 text-xs text-ink-faint">
            <p>{t("impactNote")}</p>
            <dl className="grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
              {Object.entries(impact.assumptions).map(([k, v]) => {
                const text = t(`as_${k}`);
                return (
                <div key={k} className="flex justify-between gap-3 border-b border-border py-1">
                  <dt>{text === `as_${k}` ? k.replace(/_/g, " ") : text}</dt>
                  <dd className="tabular-nums text-ink-muted" dir="ltr">
                    {v.toLocaleString("en-US")}
                  </dd>
                </div>
                );
              })}
            </dl>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
