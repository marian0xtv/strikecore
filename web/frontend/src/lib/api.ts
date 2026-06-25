const BASE = "";  // same-origin (FastAPI mounts dist/ at /)

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) throw new Error(`API ${path} → ${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export type Dossier = {
  id: number; status: string; pir_question: string; target?: string;
  target_kind?: string; bluf?: string; finding_count?: number; run_count?: number;
  cost_micros?: number; created_at: string; completed_at?: string;
};
export type Agent = {
  name: string; family: string; domain?: string; description: string;
  cost_estimate_micros: number; metadata?: Record<string, any>;
};
export type Run = {
  id: number; dossier_id?: number; role: string; agent_name: string;
  status: string; started_at: string; ended_at?: string; cost_micros: number;
};
export type Trace = {
  id: number; ts: string; level: string; event: string; agent_run_id?: number;
  payload: any;
};
export type Improvement = {
  id: number; agent_run_id?: number; category: string; target_component: string;
  description: string; evidence_count: number; applied: boolean; created_at: string;
};
export type TokensSummary = {
  totals: { calls: number; input_tokens: number; output_tokens: number;
            cached_tokens: number; cost_micros: number };
  by_model: any[]; by_day: any[]; cache_hit_rate_7d: number;
};

export type HephTool = {
  name: string; url: string; stars?: number; language?: string;
  reliability: string; confidence: number; signal?: string;
};
export type HephModelUsage = {
  task_type: string; model: string; reason?: string; calls: number;
  input_tokens?: number; output_tokens?: number; cost_micros: number;
};
export type HephRun = {
  run_id: string; status: string; started_at: string; finished_at: string;
  params: { focus_category: string; depth: number; dry_run: boolean;
            profile: string; lethality: string };
  candidates: HephTool[];
  research: { claim: string; source?: string; kind: string }[];
  gap_analysis: { covered: string[]; gaps: string[]; target_gap?: string };
  decisions: { candidate: string; action: string; rationale: string }[];
  pending_approvals: { gate: string; reason: string; candidate?: string }[];
  routing: { profile: string; policy: any; lethality: string };
  model_usage: HephModelUsage[];
  totals: { calls: number; cost_usd_micros: number };
};
export type HephRunsResp = {
  runs: HephRun[]; latest: HephRun | null;
  pending: ({ run_id: string; gate: string; reason: string; candidate?: string })[];
};
export type TokensByMode = {
  by_mode: { task_type: string; model: string; calls: number;
             input_tokens?: number; output_tokens?: number; cost_micros: number }[];
};

export type CRRun = {
  run_id: string; agent: string; surface: string; phase?: string;
  effective_status: string; is_active: boolean; elapsed_seconds: number;
  calls: number; input_tokens: number; output_tokens: number;
  cost_micros: number; pending_gate_count: number; pending_gates: string[];
  last_detail?: string; params?: Record<string, any>; last_seen?: number;
};
export type CRState = {
  generated_at: string;
  aggregates: {
    active_agents: number; total_runs: number; llm_calls: number;
    calls_per_min: number; cost_micros: number; pending_gates: number;
    models_in_use: Record<string, number>;
  };
  runs: CRRun[];
};
export type CREvent = {
  ts: string; event_type: string; detail?: string; model?: string;
  cost_micros?: number; gate?: string; phase?: string;
};
export type CRDetail = { run: CRRun & { missing?: boolean }; timeline: CREvent[] };

export const fmtUsd = (micros?: number | string | null) =>
  micros == null ? "—" : "$" + (Number(micros) / 1_000_000).toFixed(4);

export const fmtElapsed = (s?: number) => {
  const n = Math.floor(s || 0);
  return `${String(Math.floor(n / 60)).padStart(2, "0")}:${String(n % 60).padStart(2, "0")}`;
};

export const fmtDate = (iso?: string) => iso ? new Date(iso).toLocaleString() : "—";
