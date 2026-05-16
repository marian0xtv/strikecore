import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Loading } from "./Home";

export default function Settings() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<any>("/api/settings") });
  if (!q.data) return <Loading state={q} />;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Settings</h1>

      <section className="card">
        <header className="card-header">Model routing</header>
        <table className="tbl">
          <thead><tr><th>Task</th><th>Preferred model</th><th>Alt chain</th><th>Success</th><th>Failure</th><th>Explore %</th></tr></thead>
          <tbody>
            {q.data.model_routing.map((r: any) => (
              <tr key={r.task_type}>
                <td className="font-mono">{r.task_type}</td>
                <td className="font-mono">{r.preferred_model}</td>
                <td className="text-xs text-muted">{Array.isArray(r.alt_model_chain) ? r.alt_model_chain.join(" → ") : "—"}</td>
                <td>{r.success_count}</td>
                <td>{r.failure_count}</td>
                <td>{(Number(r.explore_pct) * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <header className="card-header">Budget buckets</header>
        <table className="tbl">
          <thead><tr><th>Name</th><th>Period</th><th>Cap (USD)</th><th>Soft cap %</th><th>At soft</th><th>At hard</th><th>Enabled</th></tr></thead>
          <tbody>
            {q.data.budget_bucket.map((b: any) => (
              <tr key={b.name}>
                <td className="font-mono">{b.name}</td>
                <td>{b.period}</td>
                <td>${(Number(b.cap_micros) / 1_000_000).toFixed(2)}</td>
                <td>{(Number(b.soft_cap_pct) * 100).toFixed(0)}%</td>
                <td>{b.action_at_soft}</td>
                <td>{b.action_at_hard}</td>
                <td>{b.enabled ? "✓" : "✗"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <header className="card-header">Schema</header>
        <div className="text-sm">
          <div>Version: <span className="font-mono text-accent">{q.data.schema_version?.version}</span></div>
          <div className="text-muted text-xs">Applied: {q.data.schema_version?.applied_at}</div>
        </div>
      </section>
    </div>
  );
}
