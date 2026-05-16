import { useQuery } from "@tanstack/react-query";
import { api, fmtUsd, TokensSummary } from "@/lib/api";

export default function TopBar() {
  const { data, isLoading } = useQuery({
    queryKey: ["tokens-summary"],
    queryFn: () => api<TokensSummary>("/api/tokens/summary"),
    refetchInterval: 15000,
  });
  const today = data?.by_day?.[0];
  const hit = data ? (data.cache_hit_rate_7d * 100).toFixed(1) + "%" : "—";

  return (
    <header className="flex h-12 items-center justify-between border-b border-line bg-panel px-4">
      <div className="text-sm text-muted">
        Hermes-style agent dashboard ·
        <span className="ml-2 text-text">atlas@10.0.0.1</span>
      </div>
      <div className="flex items-center gap-4 text-xs text-muted">
        <span>Today: <span className="text-text">{today ? `${today.calls} calls / ${fmtUsd(today.cost_micros)}` : "—"}</span></span>
        <span>Cache hit (7d): <span className="text-good">{hit}</span></span>
        <span className={isLoading ? "text-warn" : "text-good"}>● live</span>
      </div>
    </header>
  );
}
