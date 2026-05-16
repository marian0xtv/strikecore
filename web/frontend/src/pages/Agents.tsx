import { useQuery } from "@tanstack/react-query";
import { api, Agent, fmtUsd } from "@/lib/api";
import { Loading } from "./Home";

export default function Agents() {
  const q = useQuery({ queryKey: ["agents-full"], queryFn: () => api<Agent[]>("/api/agents") });
  const families = q.data ? Array.from(new Set(q.data.map(a => a.family))) : [];

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Subagent Registry</h1>
      <p className="text-sm text-muted">Every callable known to the orchestrator: intel_team specialists, legacy agents, and (Phase D) binary tools.</p>
      {!q.data ? <Loading state={q} /> : (
        families.map(fam => {
          const tools = q.data!.filter(a => a.family === fam);
          return (
            <section className="card" key={fam}>
              <header className="card-header">
                <span>{fam}</span>
                <span className="text-muted text-xs font-normal">{tools.length} tool(s)</span>
              </header>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {tools.map(t => (
                  <div key={t.name} className="rounded border border-line bg-bg p-3">
                    <div className="flex items-center justify-between">
                      <div className="font-semibold text-text">{t.name}</div>
                      <span className="text-[10px] text-muted">{fmtUsd(t.cost_estimate_micros)}/call</span>
                    </div>
                    {t.domain && <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">domain: {t.domain}</div>}
                    <p className="mt-2 text-xs text-muted line-clamp-3">{t.description}</p>
                    {t.metadata?.class && (
                      <div className="mt-2 text-[10px] font-mono text-muted/80 truncate">{t.metadata.class}</div>
                    )}
                  </div>
                ))}
              </div>
            </section>
          );
        })
      )}
    </div>
  );
}
