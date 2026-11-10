# BerthIQ — Web

Next.js (App Router, TypeScript, Tailwind) dashboard for the BerthIQ congestion advisory pipeline.

## Structure

```
src/
  app/                      routes (App Router)
    page.tsx                port board (home): live tier, 24 h sparkline, idle-cost estimate
    port/[portId]/page.tsx  single port: live signal + advisory pipeline + evidence + impact
    alerts/page.tsx         Alerts Center: autonomous alerts, AI drafts, approve/reject/resolve
  components/
    ui/                     generic primitives — Button, Card, Badge, TierBadge,
                             MetricTile, NumberField, EmptyState, Skeleton, ErrorBanner
    board/                  port board — PortCard, PortBoard, LiveSignalPanel, ShipMap
    advisory/               advisory pipeline UI — PortAdvisoryView, AdvisoryCard,
                             LoadingSteps, EvidencePanel, ImpactPanel
    alerts/                 AlertsCenter, AlertCard (human-in-the-loop workflow)
    LocaleProvider.tsx      English/Arabic switch; sets page direction (LTR/RTL)
  lib/
    api.ts                  typed fetch client for the backend
    types.ts                shared types (mirrors the backend Pydantic models)
    tier.ts                 tier/persona display mappings
    hooks.ts                live-data and alert polling hooks
    format.ts               currency, number and relative-time formatting (EN/AR)
    i18n.ts                 UI strings and per-locale text direction
```

## Setup

```bash
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_BERTHIQ_API_URL if not using the default
npm run dev
```

Open http://localhost:3000. Requires the [backend](../backend) running.
