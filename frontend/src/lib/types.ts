export type CongestionTier = "Low" | "Medium" | "High" | "Critical";

export type Persona = "carrier" | "trucking_company" | "terminal_operator";

export interface PortSummary {
  port_id: string;
  name: string;
  country: string;
  live_coverage: boolean;
}

export interface Ship {
  id: string;
  lat: number;
  lon: number;
  speed_knots: number;
  waiting: boolean;
  at_berth: boolean;
}

export interface LiveVesselQueue {
  port_id: string;
  port_name: string;
  country: string;
  live_coverage: boolean;
  vessel_queue_length: number;
  vessels_at_berth: number;
  vessels_observed: number;
  source: string;
  bounding_box: [[number, number], [number, number]];
  center: [number, number];
  coverage_note: string;
  connected: boolean;
  warming_up: boolean;
  last_error: string | null;
  ships?: Ship[];
  // Added by the backend from the same rule-based classifier the agents use.
  // null when the port has no live coverage or is still warming up.
  tier: CongestionTier | null;
  metric_tiers: Partial<Record<MetricKey, CongestionTier>> | null;
  trend: TrendPoint[];
  idle_cost_usd: number | null;
  queue_baseline: number | null; // the port's usual queue (median of history); null until ~1 h of data
  avg_waiting_time_hours?: number;
  berth_occupancy_rate?: number;
}

export type MetricKey = "berth_occupancy_rate" | "vessel_queue_length" | "avg_waiting_time_hours";

export interface TrendPoint {
  ts: number;
  queue: number;
  tier: CongestionTier;
}

export interface PortSnapshot {
  port_name: string;
  berth_occupancy_rate: number;
  vessel_queue_length: number;
  avg_waiting_time_hours: number;
  language?: "en" | "ar";
}

export interface Recommendation {
  persona: Persona;
  action: string;
  reasoning: string;
}

export interface Precedent {
  id: string;
  port_name: string;
  tier: string;
  summary: string;
  outcome: string;
}

export interface Evidence {
  metrics: Record<MetricKey, number>;
  metric_tiers: Partial<Record<MetricKey, CongestionTier>>; // missing = shown but not used for the tier
  thresholds: Record<MetricKey, { Low: number; Medium: number; High: number }>;
  driving_metrics: MetricKey[];
  queue_baseline: number | null;
  precedent_ids: string[];
}

export interface Impact {
  idle: { ships_waiting: number; idle_ship_hours: number; idle_cost_usd: number };
  jit_per_ship: {
    service_speed_kn: number;
    recommended_speed_kn: number;
    wait_absorbed_hours: number;
    fuel_saved_t: number;
    co2_saved_t: number;
    cost_saved_usd: number;
  };
  assumptions: Record<string, number>;
  is_estimate: boolean;
}

export interface AdvisoryResult {
  tier: CongestionTier;
  tier_reasoning: string;
  precedents: Precedent[];
  recommendations: Recommendation[];
  advisories: Record<Persona, string>;
  evidence: Evidence;
  impact: Impact;
  ai_status?: "ok" | "fallback"; // "fallback": Claude unavailable, standard rule-based advice
  ai_error?: string | null;
  usage?: AdvisoryUsage;
}

export interface AdvisoryUsage {
  model: string;
  claude_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  latency_s: number;
}

export type AlertType = "congestion_escalation" | "anchor_drag" | "weather_risk";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type AdvisoryStatus = "none" | "generating" | "pending_approval" | "approved" | "rejected" | "failed" | "expired";

export interface AlertLogEntry {
  at: number;
  action: string;
  by: string;
  note: string | null;
}

export interface Alert {
  id: string;
  type: AlertType;
  port_id: string;
  port_name: string;
  severity: CongestionTier;
  title: Record<"en" | "ar", string>;
  message: Record<"en" | "ar", string>;
  evidence: Record<string, unknown>;
  snapshot: PortSnapshot | null; // only set for alert types the agents can advise on
  demo: boolean;
  created_at: number;
  status: AlertStatus;
  advisory_status: AdvisoryStatus;
  advisory: AdvisoryResult | null;
  advisory_error: string | null;
  log: AlertLogEntry[];
}
