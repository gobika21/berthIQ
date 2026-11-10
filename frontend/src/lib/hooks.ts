"use client";

import { useCallback, useEffect, useState } from "react";
import { useLocale } from "@/components/LocaleProvider";
import { api, ApiError } from "./api";
import type { Alert, LiveVesselQueue } from "./types";

const POLL_INTERVAL_MS = 20_000;

interface LiveQueryState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export function useLiveVesselQueues() {
  const { locale, t } = useLocale();
  const [state, setState] = useState<LiveQueryState<LiveVesselQueue[]>>({
    data: null,
    loading: true,
    error: null,
  });

  const refresh = useCallback(async () => {
    try {
      const data = await api.liveVesselQueueAll(locale);
      setState({ data, loading: false, error: null });
    } catch (e) {
      setState((prev) => ({
        data: prev.data,
        loading: false,
        error: e instanceof ApiError ? e.message : t("failedToLoad"),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { ...state, refresh };
}

export function useLiveVesselQueue(portId: string, withPositions = false) {
  const { locale, t } = useLocale();
  const [state, setState] = useState<LiveQueryState<LiveVesselQueue>>({
    data: null,
    loading: true,
    error: null,
  });

  const refresh = useCallback(async () => {
    try {
      const data = await api.liveVesselQueue(portId, withPositions, locale);
      setState({ data, loading: false, error: null });
    } catch (e) {
      setState((prev) => ({
        data: prev.data,
        loading: false,
        error: e instanceof ApiError ? e.message : t("failedToLoad"),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portId, withPositions, locale]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return { ...state, refresh };
}

const ALERT_POLL_INTERVAL_MS = 10_000;

/** All alerts, newest first, refreshed every 10 s (alerts are raised by the backend monitor). */
export function useAlerts() {
  const { t } = useLocale();
  const [state, setState] = useState<LiveQueryState<Alert[]>>({ data: null, loading: true, error: null });

  const refresh = useCallback(async () => {
    try {
      const data = await api.listAlerts();
      setState({ data, loading: false, error: null });
    } catch (e) {
      setState((prev) => ({
        data: prev.data,
        loading: false,
        error: e instanceof ApiError ? e.message : t("failedToLoadAlerts"),
      }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, ALERT_POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  /** Replace one alert in place after an action, without waiting for the next poll. */
  const replace = useCallback((alert: Alert) => {
    setState((prev) => ({ ...prev, data: prev.data?.map((a) => (a.id === alert.id ? alert : a)) ?? [alert] }));
  }, []);

  return { ...state, refresh, replace };
}
