import { useQuery } from "@tanstack/react-query";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { api, fmtUsd, fmtDate, HephRunsResp, TokensByMode } from "../lib/api";
import { Loading } from "./Home";

const modelBadge = (m: string) =>
  m.includes("fable") ? "badge badge-bad"
    : m.includes("opus") ? "badge badge-info"
      : m.includes("haiku") ? "badge badge-good" : "badge";

const relBadge = (r: string) =>
  r <= "B" ? "badge badge-good" : r === "C" ? "badge badge-info" : "badge badge-warn";

export default function Hephaestus() {
  const runsQ = useQuery({
    queryKey: ["heph-runs"],
    queryFn: () => api<HephRunsResp>("/api/hephaestus/runs?limit=20"),
    refetchInterval: 8000,
  });
  const modeQ = useQuery({
    queryKey: ["tokens-by-mode"],
    queryFn: () => api<TokensByMode>("/api/tokens/by-mode"),
    refetchInterval: 8000,
  });

  if (!runsQ.data) return <Loading state={runsQ} />;
  const { runs, latest, pending } = runsQ.data;
  const byMode = modeQ.data?.by_mode ?? [];
  const dossierRows = byMode.filter((r) =>
    r.task_type.startsWith("specialist:") || r.task_type === "planner" ||
    r.task_type === "critic");

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-baseline justify-between">
        <h1 className="text-xl font-bold">⚒ Hephaestus — Toolsmith</h1>
        <span className="text-xs text-muted">
          {runs.length} run(s){latest ? ` · latest ${fmtDate(latest.started_at)}` : ""}
        </span>
      </div>

      {/* Pending H1/H3 approvals */}
      {pending.length > 0 && (
        <section className="card">
          <header className="card-header"><span>Pending approvals (H1/H3)</span>
            <span className="badge badge-warn">{pending.length}</span></header>
          <table className="tbl">
            <thead><tr><th>Gate</th><th>Run</th><th>Candidate</th><th>Reason</th></tr></thead>
            <tbody>
              {pending.map((p, i) => (
                <tr key={i}>
                  <td><span className="badge badge-bad">{p.gate}</span></td>
                  <td className="font-mono text-xs">{p.run_id}</td>
                  <td>{p.candidate ?? "—"}</td>
                  <td className="text-muted">{p.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="px-3 py-2 text-xs text-muted">
            Approve from the CLI: <code>hephaestus approve &lt;run_id&gt; &lt;H1|H3&gt;</code>
          </div>
        </section>
      )}

      {!latest && (
        <div className="text-muted">No runs yet. Run <code>hephaestus run --focus document</code>.</div>
      )}

      {latest && (
        <>
          {/* Active routing + run summary */}
          <section className="card">
            <header className="card-header"><span>Latest run · {latest.params.focus_category}</span>
              <span className="text-muted text-xs font-normal">{latest.run_id}</span></header>
            <div className="grid grid-cols-2 gap-3 p-3 md:grid-cols-4">
              <Stat label="Status" value={latest.status} />
              <Stat label="Profile" value={latest.routing.profile} />
              <Stat label="Lethality" value={latest.routing.lethality} />
              <Stat label="Run cost" value={fmtUsd(latest.totals.cost_usd_micros)} />
            </div>
          </section>

          {/* Discovered tools w/ Admiralty */}
          <section className="card">
            <header className="card-header"><span>Discovered tools</span>
              <span className="text-muted text-xs font-normal">{latest.candidates.length}</span></header>
            <div className="grid grid-cols-1 gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
              {latest.candidates.map((c) => (
                <div key={c.url} className="rounded border border-line bg-bg p-3">
                  <div className="flex items-center justify-between">
                    <a href={c.url} target="_blank" className="text-accent text-sm">{c.name}</a>
                    <span className={relBadge(c.reliability)}>{c.reliability}{c.confidence}</span>
                  </div>
                  <div className="mt-1 text-xs text-muted">{c.signal}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Per-step model usage + cost (the model badges + routing reason) */}
          <section className="card">
            <header className="card-header"><span>Model usage &amp; cost (per step)</span>
              <span className="text-muted text-xs font-normal">{fmtUsd(latest.totals.cost_usd_micros)}</span></header>
            <table className="tbl">
              <thead><tr><th>Step (task_type)</th><th>Model</th><th>Calls</th><th>Cost</th><th>Routing reason</th></tr></thead>
              <tbody>
                {latest.model_usage.map((u) => (
                  <tr key={u.task_type}>
                    <td className="font-mono text-xs">{u.task_type}</td>
                    <td><span className={modelBadge(u.model)}>{u.model}</span></td>
                    <td>{u.calls}</td>
                    <td>{fmtUsd(u.cost_micros)}</td>
                    <td className="text-muted text-xs">{u.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {/* Decisions */}
          {latest.decisions.length > 0 && (
            <section className="card">
              <header className="card-header"><span>Decisions</span></header>
              <table className="tbl">
                <thead><tr><th>Action</th><th>Candidate</th><th>Rationale</th></tr></thead>
                <tbody>
                  {latest.decisions.map((d, i) => (
                    <tr key={i}>
                      <td><span className="badge badge-info">{d.action}</span></td>
                      <td>{d.candidate}</td>
                      <td className="text-muted">{d.rationale}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
        </>
      )}

      {/* Dossier-mode lethality cost view (other-mode router telemetry) */}
      <section className="card">
        <header className="card-header"><span>Dossier mode — analysis routing &amp; cost</span>
          <span className="text-muted text-xs font-normal">by task_type · token_ledger</span></header>
        {dossierRows.length === 0 ? (
          <div className="px-3 py-4 text-muted text-sm">
            No dossier-mode calls recorded yet. Run a dossier; the lethality profile
            routes analysis steps (ACH / synthesis) to Fable, bulk extraction to Haiku.
          </div>
        ) : (
          <>
            <div className="h-56 p-3">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={dossierRows.map((r) => ({
                  step: r.task_type, cost: Number(r.cost_micros) / 1_000_000 }))}>
                  <CartesianGrid stroke="#1d2330" />
                  <XAxis dataKey="step" stroke="#8a93a6" fontSize={10} />
                  <YAxis stroke="#8a93a6" fontSize={10} />
                  <Tooltip contentStyle={{ background: "#11151c", border: "1px solid #1d2330" }} />
                  <Bar dataKey="cost" fill="#7ab7ff" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <table className="tbl">
              <thead><tr><th>Step</th><th>Model</th><th>Calls</th><th>Cost</th></tr></thead>
              <tbody>
                {dossierRows.map((r, i) => (
                  <tr key={i}>
                    <td className="font-mono text-xs">{r.task_type}</td>
                    <td><span className={modelBadge(r.model)}>{r.model}</span></td>
                    <td>{r.calls}</td>
                    <td>{fmtUsd(r.cost_micros)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-line bg-bg p-3">
      <div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
      <div className="mt-1 text-sm font-semibold text-text">{value}</div>
    </div>
  );
}
