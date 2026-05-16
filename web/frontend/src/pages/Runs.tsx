import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Run, fmtDate, fmtUsd } from "@/lib/api";
import { Loading, StatusBadge } from "./Home";

type LiveTrace = { event: string; channel: string; payload: any };

export default function Runs() {
  const q = useQuery({ queryKey: ["runs", 100], queryFn: () => api<Run[]>("/api/runs?limit=100"), refetchInterval: 4000 });
  const [live, setLive] = useState<LiveTrace[]>([]);

  useEffect(() => {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/traces");
    ws.onmessage = (e) => {
      try {
        const m = JSON.parse(e.data);
        if (m.event === "trace") setLive(prev => [m, ...prev].slice(0, 60));
      } catch {}
    };
    ws.onerror = () => {};
    return () => ws.close();
  }, []);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Runs · Traces</h1>

      <section className="card">
        <header className="card-header">
          <span>Live trace stream (WebSocket)</span>
          <span className="text-muted text-xs font-normal">{live.length} recent events</span>
        </header>
        {live.length === 0 ? (
          <div className="text-muted text-sm">Waiting for events… (submit a dossier from Console to populate)</div>
        ) : (
          <div className="space-y-1 max-h-72 overflow-auto scrollbar-thin font-mono text-xs">
            {live.map((m, i) => (
              <div key={i} className="rounded border border-line/50 px-2 py-1">
                <span className="text-accent">{m.payload?.event || "?"}</span>
                <span className="ml-2 text-muted">run={m.payload?.agent_run_id}</span>
                <span className="ml-2 text-muted">{m.payload?.ts}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <header className="card-header">Agent runs</header>
        {!q.data ? <Loading state={q} /> : (
          <table className="tbl">
            <thead><tr><th>ID</th><th>Dossier</th><th>Role</th><th>Agent</th><th>Status</th><th>Cost</th><th>Started</th></tr></thead>
            <tbody>
              {q.data.map(r => (
                <tr key={r.id}>
                  <td><Link to={`/runs/${r.id}`} className="text-accent hover:underline">#{r.id}</Link></td>
                  <td>{r.dossier_id ? <Link className="text-accent hover:underline" to={`/dossiers/${r.dossier_id}`}>#{r.dossier_id}</Link> : "—"}</td>
                  <td><span className="badge badge-info">{r.role}</span></td>
                  <td className="text-muted truncate max-w-xs">{r.agent_name}</td>
                  <td><StatusBadge s={r.status} /></td>
                  <td>{fmtUsd(r.cost_micros)}</td>
                  <td className="text-xs text-muted">{fmtDate(r.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
