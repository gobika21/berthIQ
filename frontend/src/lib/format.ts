import type { Locale } from "./i18n";

const intlLocale = (locale: Locale) => (locale === "ar" ? "ar-AE" : "en-US");

export function formatUsd(value: number, locale: Locale): string {
  return new Intl.NumberFormat(intlLocale(locale), {
    style: "currency",
    currency: "USD",
    notation: value >= 100_000 ? "compact" : "standard",
    maximumFractionDigits: value >= 100_000 ? 1 : 0,
  }).format(value);
}

export function formatNumber(value: number, locale: Locale, digits = 1): string {
  return new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: digits }).format(value);
}

export function timeAgo(epochSeconds: number, locale: Locale): string {
  const rtf = new Intl.RelativeTimeFormat(intlLocale(locale), { numeric: "auto" });
  const diff = epochSeconds - Date.now() / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), "second");
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

/** Fill "{name}" placeholders in a translated string. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k) => String(values[k] ?? `{${k}}`));
}

/** Spoken/text summary of a 24 h queue trend, for screen readers. */
export function describeTrend(points: { queue: number }[], template: string): string {
  if (points.length < 2) return "";
  const first = points[0]!.queue;
  const last = points[points.length - 1]!.queue;
  const max = Math.max(...points.map((p) => p.queue));
  return fill(template, { from: first, to: last, max });
}
