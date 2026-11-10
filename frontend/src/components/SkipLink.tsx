"use client";

import { useLocale } from "@/components/LocaleProvider";

/** First focusable element on every page: lets keyboard users jump past the header. */
export function SkipLink() {
  const { t } = useLocale();
  return (
    <a
      href="#main-content"
      className="sr-only focus:not-sr-only focus:fixed focus:start-4 focus:top-3 focus:z-[100] focus:rounded-sm focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-canvas"
    >
      {t("skipToContent")}
    </a>
  );
}
