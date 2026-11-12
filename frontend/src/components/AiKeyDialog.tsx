"use client";

import { useEffect, useId, useRef, useState } from "react";
import { KeyRound, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { useLocale } from "@/components/LocaleProvider";
import { api } from "@/lib/api";
import { getAiKey, KEY_PATTERN, onAiKeyChange, onOpenAiKeyDialog, setAiKey } from "@/lib/aiKey";
import { fill } from "@/lib/format";
import type { AiQuota } from "@/lib/types";

/** Header button plus the dialog where a visitor adds their own Anthropic key. */
export function AiKeyButton({ className }: { className: string }) {
  const { t } = useLocale();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputId = useId();
  const errorId = useId();
  const [hasKey, setHasKey] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [quota, setQuota] = useState<AiQuota | null>(null);

  // Read after mount so the server-rendered HTML and first client render agree.
  useEffect(() => {
    const sync = () => setHasKey(Boolean(getAiKey()));
    sync();
    const offChange = onAiKeyChange(sync);
    const offOpen = onOpenAiKeyDialog(() => open());
    return () => {
      offChange();
      offOpen();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function open() {
    setDraft("");
    setError(null);
    api.aiQuota().then(setQuota).catch(() => setQuota(null));
    dialogRef.current?.showModal();
  }

  function close() {
    dialogRef.current?.close();
  }

  function save() {
    const key = draft.trim();
    if (!KEY_PATTERN.test(key)) {
      setError(t("aiKeyInvalid"));
      return;
    }
    setAiKey(key);
    close();
  }

  const quotaLine =
    quota == null
      ? null
      : quota.free_runs_per_day === 0
        ? t("aiKeyNoFreeRuns")
        : fill(t("aiKeyFreeRunsLeft"), { left: quota.free_runs_left, total: quota.free_runs_per_day });

  return (
    <>
      <button
        type="button"
        onClick={open}
        className={className}
        aria-label={hasKey ? t("aiKeyButtonSet") : t("aiKeyButton")}
        title={hasKey ? t("aiKeyButtonSet") : t("aiKeyButton")}
      >
        <KeyRound className="h-3.5 w-3.5" strokeWidth={2} aria-hidden="true" />
        <span className="hidden sm:inline">{t("aiKeyShort")}</span>
        {hasKey && <span className="h-1.5 w-1.5 rounded-full bg-tier-low" aria-hidden="true" />}
      </button>

      <dialog
        ref={dialogRef}
        aria-labelledby={`${inputId}-title`}
        className="w-[min(92vw,440px)] rounded-md border border-border bg-canvas p-0 text-ink shadow-raised backdrop:bg-black/60"
      >
        <form
          method="dialog"
          className="flex flex-col gap-4 p-5"
          onSubmit={(e) => {
            e.preventDefault();
            save();
          }}
        >
          <div className="flex items-start justify-between gap-3">
            <h2 id={`${inputId}-title`} className="text-base font-semibold">
              {t("aiKeyTitle")}
            </h2>
            <button
              type="button"
              onClick={close}
              aria-label={t("close")}
              className="rounded-sm p-1 text-ink-muted hover:bg-sunken hover:text-ink"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          </div>

          <p className="text-sm leading-relaxed text-ink-muted">{t("aiKeyIntro")}</p>
          {quotaLine && <p className="text-sm font-medium text-ink">{quotaLine}</p>}

          {hasKey ? (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-ink">{t("aiKeyInUse")}</p>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setAiKey(null);
                    close();
                  }}
                >
                  {t("aiKeyRemove")}
                </Button>
                <Button type="button" variant="ghost" onClick={close}>
                  {t("close")}
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <label htmlFor={inputId} className="text-xs font-medium text-ink">
                {t("aiKeyLabel")}
              </label>
              <input
                id={inputId}
                type="password"
                autoComplete="off"
                spellCheck={false}
                placeholder="sk-ant-…"
                value={draft}
                onChange={(e) => {
                  setDraft(e.target.value);
                  setError(null);
                }}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                className="rounded-sm border border-border bg-surface px-3 py-2 font-mono text-sm text-ink placeholder:text-ink-faint focus:border-accent focus:outline-none"
              />
              {error && (
                <p id={errorId} className="text-xs text-tier-critical">
                  {error}
                </p>
              )}
              <a
                href="https://console.anthropic.com/settings/keys"
                target="_blank"
                rel="noreferrer"
                className="self-start text-xs font-medium text-accent hover:underline"
              >
                {t("aiKeyGetOne")}
              </a>
              <div className="mt-1 flex gap-2">
                <Button type="submit">{t("aiKeySave")}</Button>
                <Button type="button" variant="ghost" onClick={close}>
                  {t("close")}
                </Button>
              </div>
            </div>
          )}

          <p className="border-t border-border pt-3 text-xs leading-relaxed text-ink-faint">{t("aiKeyPrivacy")}</p>
        </form>
      </dialog>
    </>
  );
}
