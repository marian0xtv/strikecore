import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, fmtDate, fmtUsd } from "@/lib/api";
import { Loading, StatusBadge } from "./Home";

export default function DossierDetail() {
  const { id } = useParams();
  const q = useQuery({
    queryKey: ["dossier", id],
    queryFn: () => api<any>(`/api/dossiers/${id}`),
    enabled: !!id,
  });
  if (!q.data) return <Loading state={q} />;
  const { dossier: d, findings, runs, improvements, cost } = q.data;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Dossier #{d.id} — {d.target || d.target_display_name || "—"}</h1>
        <p className="text-sm text-muted mt-1">{d.pir_question}</p>
      </div>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Stat label="Status"   value={<StatusBadge s={d.status} />} />
        <Stat label="Created"  value={fmtDate(d.created_at)} />
        <Stat label="Done"     value={fmtDate(d.completed_at)} />
        <Stat label="Cost"     value={fmtUsd(cost.cost_micros)} />
      </div>

      {d.bluf && (
        <section className="card">
          <header className="card-header">BLUF</header>
          <p className="whitespace-pre-wrap text-sm text-text">{d.bluf}</p>
        </section>
      )}

      <section className="card">
        <header className="card-header">Findings ({findings.length})</header>
        {findings.length === 0 ? <div className="text-muted text-sm">no findings persisted</div> :
        <table className="tbl">
          <thead><tr><th>Domain</th><th>Type</th><th>Value</th><th>Conf</th><th>Notes</th></tr></thead>
          <tbody>
            {findings.map((f: any) => (
              <tr key={f.id}>
                <td><span className="badge badge-info">{f.domain}</span></td>
                <td>{f.finding_type}</td>
                <td className="truncate max-w-xs">{f.value}</td>
                <td>{Number(f.confidence).toFixed(2)}</td>
                <td className="text-muted text-xs">{f.notes}</td>
              </tr>
            ))}
          </tbody>
        </table>}
      </section>

      <section className="card">
        <header className="card-header">Runs ({runs.length})</header>
        <table className="tbl">
          <thead><tr><th>ID</th><th>Role</th><th>Agent</th><th>Status</th><th>Cost</th></tr></thead>
          <tbody>
            {runs.map((r: any) => (
              <tr key={r.id}>
                <td><Link to={`/runs/${r.id}`} className="text-accent hover:underline">#{r.id}</Link></td>
                <td><span className="badge badge-info">{r.role}</span></td>
                <td className="text-muted">{r.agent_name}</td>
                <td><StatusBadge s={r.status} /></td>
                <td>{fmtUsd(r.cost_micros)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {improvements.length > 0 && (
        <section className="card">
          <header className="card-header">Improvements ({improvements.length})</header>
          <table className="tbl">
            <thead><tr><th>Category</th><th>Target</th><th>Description</th><th>Evidence</th><th>Applied</th></tr></thead>
            <tbody>
              {improvements.map((i: any) => (
                <tr key={i.id}>
                  <td><span className="badge badge-warn">{i.category}</span></td>
                  <td className="text-muted">{i.target_component}</td>
                  <td className="text-xs">{i.description}</td>
                  <td>{i.evidence_count}</td>
                  <td>{i.applied ? "✓" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return <div className="card"><div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
    <div className="mt-1 text-base">{value}</div></div>;
}
