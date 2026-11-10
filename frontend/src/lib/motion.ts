/**
 * User-controlled pause for decorative animation (WCAG 2.2.2 Pause, Stop, Hide).
 * Stored per browser and broadcast with a window event, so the header toggle and
 * the background canvas stay in sync without sharing React state.
 */

const STORAGE_KEY = "berthiq-motion-paused";
const EVENT = "berthiq:motion";

export function isMotionPaused(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setMotionPaused(paused: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, paused ? "1" : "0");
  } catch {
    // Storage blocked (private mode): the toggle still works for this page view.
  }
  window.dispatchEvent(new CustomEvent<boolean>(EVENT, { detail: paused }));
}

export function onMotionChange(callback: (paused: boolean) => void): () => void {
  const handler = (e: Event) => callback((e as CustomEvent<boolean>).detail);
  window.addEventListener(EVENT, handler);
  return () => window.removeEventListener(EVENT, handler);
}
