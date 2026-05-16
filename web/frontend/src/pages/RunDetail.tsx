import { useQuery } from "@tanstack/react-query";
import { useParams, Link } from "react-router-dom";
import { api, fmtDate, fmtUsd } from "@/lib/api";
import { Loading, StatusBadge } from "./Home";

export default function RunDetail() {
  const { id } = useParams();
  const q = useQuery({ queryKey: ["run", id], queryFn: () => api<any>(`/api/runs/${id}`), enabled: !!id });
  if (!q.data) return <Loading state={q} />;
  const { run: r, invocations, traces } = q.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Run #{r.id} — {r.role} · <span className="text-muted">{r.agent_name}</span></h1>
        <div className="text-sm text-muted mt-1">
          {r.dossier_id && <Link className="text-accent hover:underline" to={`/dossiers/${r.dossier_id}`}>← dossier #{r.dossier_id}</Link>}
          <span className="ml-3">Started {fmtDate(r.started_at)} · Ended {fmtDate(r.ended_at)} · {fmtUsd(r.cost_micros)}</span>
          <span className="ml-3"><StatusBadge s={r.status} /></span>
        </div>
      </div>

      <section className="card">
        <header className="card-header">Subagent invocations ({invocations.length})</header>
        {invocations.length === 0 ? <div className="text-muted text-sm">none</div> :
        <table className="tbl">
          <thead><tr><th>ID</th><th>Tool</th><th>OK</th><th>Duration (ms)</th><th>Cost</th><th>Error</th></tr></thead>
          <tbody>
            {invocations.map((i: any) => (
              <tr key={i.id}>
                <td>#{i.id}</td><td className="font-mono">{i.tool_name}</td>
                <td>{i.success ? "✓" : "✗"}</td>
                <td>{i.duration_ms}</td>
                <td>{fmtUsd(i.cost_micros)}</td>
                <td className="text-bad text-xs truncate max-w-xs">{i.error_text || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>}
      </section>

      <section className="card">
        <header className="card-header">Traces (latest {traces.length})</header>
        <div className="space-y-1 max-h-[500px] overflow-auto scrollbar-thin font-mono text-xs">
          {traces.map((t: any) => (
            <div key={t.id} className="rounded border border-line/50 px-2 py-1">
              <span className={t.level === "error" ? "text-bad" : t.level === "warn" ? "text-warn" : "text-accent"}>
                {t.event}
              </span>
              <span className="ml-2 text-muted">{fmtDate(t.ts)}</span>
              {t.payload && Object.keys(t.payload).length > 0 && (
                <div className="text-muted/70 mt-0.5 break-all">{JSON.stringify(t.payload).slice(0, 240)}</div>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
