import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmtUsd, TokensSummary } from "@/lib/api";
import { Loading } from "./Home";

export default function Cost() {
  const q = useQuery({ queryKey: ["tokens-cost"], queryFn: () => api<TokensSummary>("/api/tokens/summary"), refetchInterval: 8000 });
  if (!q.data) return <Loading state={q} />;
  const t = q.data;
  const totalCost = Number(t.totals.cost_micros || 0);
  const hit = (t.cache_hit_rate_7d * 100).toFixed(1);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Cost · Tokens</h1>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <Stat label="LLM calls (lifetime)"     value={t.totals.calls.toLocaleString()} />
        <Stat label="Input tokens (lifetime)"  value={Number(t.totals.input_tokens).toLocaleString()} />
        <Stat label="Output tokens (lifetime)" value={Number(t.totals.output_tokens).toLocaleString()} />
        <Stat label="Cache hit rate (7d)"      value={`${hit}%`} />
      </div>

      <section className="card">
        <header className="card-header">Spend last 30 days</header>
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={[...t.by_day].reverse().map((d: any) => ({ day: String(d.day).slice(5), usd: Number(d.cost_micros) / 1_000_000 }))}>
              <CartesianGrid stroke="#1d2330" strokeDasharray="3 3" />
              <XAxis dataKey="day" stroke="#8a93a6" fontSize={10} />
              <YAxis stroke="#8a93a6" fontSize={10} />
              <Tooltip contentStyle={{ background: "#11151c", border: "1px solid #1d2330" }} />
              <Bar dataKey="usd" fill="#7ab7ff" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="card">
        <header className="card-header">Cost by model · lifetime {fmtUsd(totalCost)}</header>
        <table className="tbl">
          <thead><tr><th>Model</th><th>Calls</th><th>Input</th><th>Output</th><th>Cached</th><th>Cost</th></tr></thead>
          <tbody>
            {t.by_model.map((m: any) => (
              <tr key={m.model}>
                <td className="font-mono">{m.model}</td>
                <td>{m.calls}</td>
                <td>{Number(m.input_tokens).toLocaleString()}</td>
                <td>{Number(m.output_tokens).toLocaleString()}</td>
                <td>{Number(m.cached_tokens).toLocaleString()}</td>
                <td>{fmtUsd(m.cost_micros)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return <div className="card"><div className="text-[10px] uppercase tracking-wider text-muted">{label}</div>
    <div className="mt-1 text-2xl font-semibold">{value}</div></div>;
}
