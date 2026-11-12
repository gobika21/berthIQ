/**
 * A visitor's own Anthropic API key, so AI advice runs on their account instead of the
 * site's small free daily allowance.
 *
 * Kept in sessionStorage only: it lives in this browser tab and is gone when the tab
 * closes. It is sent to the BerthIQ backend in the X-Anthropic-Key header on the
 * requests that call Claude, and the backend uses it for that request only.
 */

const STORAGE_KEY = "berthiq-anthropic-key";
const CHANGE_EVENT = "berthiq:ai-key";
const OPEN_EVENT = "berthiq:open-ai-key";

export const KEY_PATTERN = /^sk-ant-[A-Za-z0-9_-]{20,200}$/;

export function getAiKey(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAiKey(key: string | null): void {
  try {
    if (key) sessionStorage.setItem(STORAGE_KEY, key);
    else sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Storage blocked: the key can't be kept, so AI runs use the free allowance.
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function onAiKeyChange(callback: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, callback);
  return () => window.removeEventListener(CHANGE_EVENT, callback);
}

/** Ask the header to open the key dialog (used by the "add your key" links in notices). */
export function openAiKeyDialog(): void {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

export function onOpenAiKeyDialog(callback: () => void): () => void {
  window.addEventListener(OPEN_EVENT, callback);
  return () => window.removeEventListener(OPEN_EVENT, callback);
}

/** Which notice to show for an advisory that fell back to standard advice. */
export function fallbackNoticeKey(aiError: string | null | undefined): string {
  if (aiError === "free_quota_used") return "aiQuotaUsedNotice";
  if (aiError === "no_key") return "aiNoKeyNotice";
  if (aiError === "AuthenticationError" || aiError === "PermissionDeniedError") return "aiKeyRejectedNotice";
  return "aiFallbackNotice";
}

/** True when adding (or fixing) a key would get the visitor AI advice next time. */
export function keyWouldHelp(aiError: string | null | undefined): boolean {
  return fallbackNoticeKey(aiError) !== "aiFallbackNotice";
}
