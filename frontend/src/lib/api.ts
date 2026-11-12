import { getAiKey } from "./aiKey";
import type { AdvisoryResult, AiQuota, Alert, AlertStatus, LiveVesselQueue, PortSnapshot, PortSummary } from "./types";

const API_URL = process.env.NEXT_PUBLIC_BERTHIQ_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {}

/** Header for requests that call Claude: the visitor's own key, when they added one. */
function aiHeaders(): Record<string, string> {
  const key = getAiKey();
  return key ? { "X-Anthropic-Key": key } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(`Could not reach the BerthIQ backend at ${API_URL}`);
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(body?.detail ?? `Request failed (${res.status})`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  listPorts: (lang = "en") => request<PortSummary[]>(`/live/ports?lang=${lang}`),
  liveVesselQueue: (portId: string, withPositions = false, lang = "en") =>
    request<LiveVesselQueue>(
      `/live/vessel-queue?port=${encodeURIComponent(portId)}&lang=${lang}${withPositions ? "&positions=true" : ""}`,
    ),
  liveVesselQueueAll: (lang = "en") => request<LiveVesselQueue[]>(`/live/vessel-queue/all?lang=${lang}`),
  runAdvisory: (snapshot: PortSnapshot) =>
    request<AdvisoryResult>("/advisory", { method: "POST", body: JSON.stringify(snapshot), headers: aiHeaders() }),
  aiQuota: () => request<AiQuota>("/ai/quota"),

  listAlerts: (status?: AlertStatus) => request<Alert[]>(`/alerts${status ? `?status=${status}` : ""}`),
  alertAction: (id: string, action: "acknowledge" | "approve" | "reject" | "resolve", note?: string) =>
    request<Alert>(`/alerts/${id}/${action}`, { method: "POST", body: JSON.stringify({ note: note ?? null }) }),
  requestAlertAdvisory: (id: string) =>
    request<Alert>(`/alerts/${id}/advisory`, { method: "POST", headers: aiHeaders() }),
  demoReplay: (portId = "rotterdam") =>
    request<Alert>(`/demo/replay?port=${encodeURIComponent(portId)}`, { method: "POST", headers: aiHeaders() }),
};
