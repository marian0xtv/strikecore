import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, fmtUsd, fmtElapsed, CRState, CRDetail } from "@/lib/api";
import { Loading } from "./Home";

const STATUS_CLS: Record<string, string> = {
  running: "text-emerald-400", paused: "text-amber-400", completed: "text-cyan-400",
  error: "text-red-400", failed: "text-red-400", stale: "text-fuchsia-400",
  cancelled: "text-muted",
};

export default function ControlRoom() {
  const [sel, setSel] = useState<string | null>(null);
  const q = useQuery({
    queryKey: ["control-room"],
    queryFn: () => api<CRState>("/api/control-room/state?limit=80"),
    refetchInterval: 2000,
  });
  const detailQ = useQuery({
    queryKey: ["control-room-run", sel],
    queryFn: () => api<CRDetail>(`/api/control-room/run/${sel}`),
    refetchInterval: 2000,
    enabled: !!sel,
  });

  if (!q.data) return <Loading state={q} />;
  const a = q.data.aggregates;
  const models = Object.entries(a.models_in_use || {})
    .map(([m, n]) => `${m.split("-")[1] || m}:${n}`).join("  ") || "—";

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Control Room</h1>
        <p className="text-[11px] text-muted">Live agent activity &amp; metrics · 2s refresh ·
          deep drill-down on Hephaestus (research → gaps → fixes → gates)</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
        <Stat label="Active agents" value={a.active_agents} cls="text-emerald-400" />
        <Stat label="Runs" value={a.total_runs} />
        <Stat label="LLM calls" value={a.llm_calls} />
        <Stat label="Calls/min" value={a.calls_per_min} cls="text-cyan-400" />
        <Stat label="Cost" value={fmtUsd(a.cost_micros)} cls="text-amber-400" />
        <Stat label="Pending gates" value={a.pending_gates}
              cls={a.pending_gates ? "text-red-400" : undefined} />
      </div>
      <div className="text-[10px] text-muted">models in use: {models}</div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <section className="card lg:col-span-2 overflow-auto">
          <header className="card-header">Agents</header>
          <table className="tbl">
            <thead><tr>
              <th>run</th><th>agent</th><th>surface</th><th>status</th><th>phase</th>
              <th className="text-right">elapsed</th><th className="text-right">calls</th>
              <th className="text-right">cost</th><th className="text-right">gates</th>
            </tr></thead>
            <tbody>
              {q.data.runs.map((r) => (
                <tr key={r.run_id} onClick={() => setSel(r.run_id)}
                    className={"cursor-pointer hover:bg-line/60 " + (sel === r.run_id ? "bg-line/50" : "")}>
                  <td className="font-mono">{r.run_id.slice(0, 8)}</td>
                  <td>{r.agent}</td>
                  <td className="text-muted">{r.surface}</td>
                  <td className={STATUS_CLS[r.effective_status] || ""}>{r.effective_status}</td>
                  <td className="text-text/80">{r.phase}</td>
                  <td className="text-right text-muted">{fmtElapsed(r.elapsed_seconds)}</td>
                  <td className="text-right">{r.calls}</td>
                  <td className="text-right text-amber-400">{fmtUsd(r.cost_micros)}</td>
                  <td className={"text-right " + (r.pending_gate_count ? "text-red-400" : "text-muted")}>
                    {r.pending_gate_count}</td>
                </tr>
              ))}
              {q.data.runs.length === 0 && (
                <tr><td colSpan={9} className="py-3 text-muted">No agent runs yet.</td></tr>
              )}
            </tbody>
          </table>
        </section>

        <section className="card overflow-auto">
          <header className="card-header">Detail</header>
          <Detail data={detailQ.data} />
        </section>
      </div>
    </div>
  );
}

function Detail({ data }: { data?: CRDetail }) {
  if (!data) return <div className="text-xs text-muted">Select a run for details.</div>;
  const run = data.run;
  if (run.missing) return <div className="text-xs text-muted">No data for this run.</div>;
  return (
    <div className="space-y-2 text-xs">
      <div className="font-semibold">{run.agent}
        <span className="text-muted"> [{run.surface}]</span>{" "}
        <span className={STATUS_CLS[run.effective_status] || ""}>{run.effective_status}</span></div>
      <div className="text-[10px] text-muted">
        {fmtElapsed(run.elapsed_seconds)} · {run.calls} call(s) ·{" "}
        <span className="text-amber-400">{fmtUsd(run.cost_micros)}</span></div>
      {run.params && (
        <div className="text-[10px] text-muted">
          params: {Object.entries(run.params).map(([k, v]) => `${k}=${v}`).join(", ")}</div>
      )}
      {run.pending_gates?.length > 0 && (
        <div className="text-[10px] text-red-400">PENDING GATES: {run.pending_gates.join(", ")}</div>
      )}
      <div className="text-[10px] uppercase tracking-wider text-muted pt-1">timeline</div>
      <div className="space-y-0.5">
        {(data.timeline || []).slice(-50).map((e, i) => {
          let det = e.detail || "";
          if (e.event_type === "llm_call") det = `${e.model || ""}  ${fmtUsd(e.cost_micros)}`;
          else if (e.event_type === "gate_request") det = `GATE ${e.gate || ""}: ${det}`;
          return (
            <div key={i} className="text-[10px]">
              <span className="text-muted">{String(e.ts).slice(11, 19)}</span>{" "}
              <span className="text-cyan-400">{e.event_type}</span>{" "}
              <span className="text-text/80">{String(det).slice(0, 90)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="card">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className={"mt-1 text-2xl font-semibold " + (cls || "")}>{value}</div>
    </div>
  );
}
