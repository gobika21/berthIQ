"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Anchor, Bell, Languages, Pause, Play } from "lucide-react";
import { AiKeyButton } from "@/components/AiKeyDialog";
import { useLocale } from "@/components/LocaleProvider";
import { LOCALE_LABEL } from "@/lib/i18n";
import { useAlerts } from "@/lib/hooks";
import { isMotionPaused, onMotionChange, setMotionPaused } from "@/lib/motion";
import { cn } from "@/lib/cn";

export function Header() {
  const { locale, toggleLocale, t } = useLocale();
  const pathname = usePathname();
  const { data: alerts } = useAlerts();
  const openCount = alerts?.filter((a) => a.status === "open").length ?? 0;

  // Read after mount so the server-rendered HTML and first client render agree.
  const [motionPaused, setPausedState] = useState(false);
  useEffect(() => {
    setPausedState(isMotionPaused());
    return onMotionChange(setPausedState);
  }, []);

  const navLink = (active: boolean) =>
    cn(
      "flex min-h-[32px] items-center gap-1.5 rounded-sm px-2 py-1 text-xs font-medium transition-colors",
      active ? "bg-accent-soft text-accent-hover" : "text-ink-muted hover:bg-sunken hover:text-ink",
    );
  const iconButton =
    "flex min-h-[32px] items-center gap-1.5 rounded-sm border border-border px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-sunken hover:text-ink";

  const portsActive = pathname === "/" || pathname.startsWith("/port");
  const alertsActive = pathname.startsWith("/alerts");

  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-page items-center gap-1.5 px-4 sm:gap-2.5 sm:px-6">
        <Link href="/" className="flex shrink-0 items-center gap-2" aria-label={t("appName")}>
          <Anchor className="h-4 w-4 text-accent" strokeWidth={2} aria-hidden="true" />
          <span className="text-[15px] font-semibold tracking-tight text-ink">{t("appName")}</span>
        </Link>
        <span className="hidden rounded-sm bg-sunken px-2 py-0.5 text-xs font-medium text-ink-muted md:inline">
          {t("tagline")}
        </span>

        <nav className="ms-auto flex items-center gap-1" aria-label={t("mainNavigation")}>
          <Link href="/" className={navLink(portsActive)} aria-current={portsActive ? "page" : undefined}>
            {t("navPorts")}
          </Link>
          <Link href="/alerts" className={navLink(alertsActive)} aria-current={alertsActive ? "page" : undefined}>
            <Bell className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
            {/* Label is visible from small screens up; always available to screen readers. */}
            <span className="sr-only sm:not-sr-only">{t("navAlerts")}</span>
            {openCount > 0 && (
              <span className="rounded-full bg-tier-critical px-1.5 text-[10px] font-semibold leading-4 text-canvas">
                {openCount}
                <span className="sr-only"> {t("openAlertsSr")}</span>
              </span>
            )}
          </Link>
        </nav>

        <AiKeyButton className={iconButton} />

        <button
          type="button"
          onClick={() => setMotionPaused(!motionPaused)}
          aria-pressed={motionPaused}
          aria-label={motionPaused ? t("resumeAnimation") : t("pauseAnimation")}
          title={motionPaused ? t("resumeAnimation") : t("pauseAnimation")}
          className={iconButton}
        >
          {motionPaused ? (
            <Play className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
          ) : (
            <Pause className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
          )}
        </button>

        <button type="button" onClick={toggleLocale} className={iconButton} aria-label={t("toggleLanguage")}>
          <Languages className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
          {LOCALE_LABEL[locale]}
        </button>
      </div>
    </header>
  );
}
