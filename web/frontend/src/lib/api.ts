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

export const fmtUsd = (micros?: number | string | null) =>
  micros == null ? "—" : "$" + (Number(micros) / 1_000_000).toFixed(4);

export const fmtDate = (iso?: string) => iso ? new Date(iso).toLocaleString() : "—";
