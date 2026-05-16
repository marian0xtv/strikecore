import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, Dossier, fmtDate, fmtUsd } from "@/lib/api";
import { Loading, StatusBadge } from "./Home";

export default function Dossiers() {
  const q = useQuery({ queryKey: ["dossiers", 100], queryFn: () => api<Dossier[]>("/api/dossiers?limit=100") });
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Dossiers</h1>
      <section className="card">
        {!q.data ? <Loading state={q} /> : (
          <table className="tbl">
            <thead>
              <tr><th>ID</th><th>Target</th><th>PIR</th><th>Status</th><th>Findings</th><th>Runs</th><th>Cost</th><th>Created</th></tr>
            </thead>
            <tbody>
              {q.data.map(d => (
                <tr key={d.id}>
                  <td><Link to={`/dossiers/${d.id}`} className="text-accent hover:underline">#{d.id}</Link></td>
                  <td>{d.target || "—"}</td>
                  <td className="text-muted text-xs max-w-md truncate">{d.pir_question}</td>
                  <td><StatusBadge s={d.status} /></td>
                  <td>{d.finding_count ?? 0}</td>
                  <td>{d.run_count ?? 0}</td>
                  <td>{fmtUsd(d.cost_micros)}</td>
                  <td className="text-xs text-muted">{fmtDate(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
