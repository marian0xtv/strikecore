import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, fmtDate, fmtUsd, Dossier, Run, TokensSummary, Agent } from "@/lib/api";

export default function Home() {
  const dossiers = useQuery({ queryKey: ["dossiers", 6], queryFn: () => api<Dossier[]>("/api/dossiers?limit=6") });
  const runs     = useQuery({ queryKey: ["runs", 8],    queryFn: () => api<Run[]>("/api/runs?limit=8") });
  const tokens   = useQuery({ queryKey: ["tokens"],     queryFn: () => api<TokensSummary>("/api/tokens/summary") });
  const agents   = useQuery({ queryKey: ["agents"],     queryFn: () => api<Agent[]>("/api/agents") });

  const totals = tokens.data?.totals;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Overview</h1>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <StatCard label="Dossiers" value={dossiers.data?.length ?? 0} />
        <StatCard label="Active agents" value={agents.data?.length ?? 0} />
        <StatCard label="LLM calls (lifetime)" value={totals?.calls ?? 0} />
        <StatCard label="Spend (lifetime)" value={totals ? fmtUsd(totals.cost_micros) : "—"} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="card">
          <header className="card-header">Recent dossiers</header>
          {dossiers.data?.length ? (
            <table className="tbl">
              <thead><tr><th>ID</th><th>Target</th><th>Status</th><th>Findings</th><th>Cost</th><th>Created</th></tr></thead>
              <tbody>
                {dossiers.data.map(d => (
                  <tr key={d.id}>
                    <td><Link to={`/dossiers/${d.id}`} className="text-accent hover:underline">#{d.id}</Link></td>
                    <td>{d.target || "—"}</td>
                    <td><StatusBadge s={d.status} /></td>
                    <td>{d.finding_count ?? 0}</td>
                    <td>{fmtUsd(d.cost_micros)}</td>
                    <td className="text-xs text-muted">{fmtDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Loading state={dossiers} />}
        </section>

        <section className="card">
          <header className="card-header">Recent runs</header>
          {runs.data?.length ? (
            <table className="tbl">
              <thead><tr><th>ID</th><th>Role</th><th>Agent</th><th>Status</th><th>Started</th></tr></thead>
              <tbody>
                {runs.data.map(r => (
                  <tr key={r.id}>
                    <td><Link to={`/runs/${r.id}`} className="text-accent hover:underline">#{r.id}</Link></td>
                    <td><span className="badge badge-info">{r.role}</span></td>
                    <td className="text-muted truncate max-w-xs">{r.agent_name}</td>
                    <td><StatusBadge s={r.status} /></td>
                    <td className="text-xs text-muted">{fmtDate(r.started_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Loading state={runs} />}
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: any }) {
  return (
    <div className="card">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}
export function StatusBadge({ s }: { s: string }) {
  const c =
    s === "completed" ? "badge-good" :
    s === "running" || s === "planning" || s === "collecting" || s === "synthesizing" ? "badge-info" :
    s === "failed" || s === "budget_exceeded" ? "badge-bad" : "badge-warn";
  return <span className={`badge ${c}`}>{s}</span>;
}
export function Loading({ state }: { state: any }) {
  if (state.isLoading) return <div className="text-muted">loading…</div>;
  if (state.error) return <div className="text-bad text-xs">{String(state.error)}</div>;
  return <div className="text-muted text-sm">no rows</div>;
}
