import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Improvement, fmtDate } from "@/lib/api";
import { Loading } from "./Home";

export default function Improvements() {
  const [cat, setCat] = useState<string>("");
  const q = useQuery({
    queryKey: ["improvements", cat],
    queryFn: () => api<Improvement[]>(`/api/improvements?limit=200${cat ? `&category=${cat}` : ""}`),
    refetchInterval: 8000,
  });
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Improvements feed</h1>
        <div className="text-xs space-x-2">
          {["", "quality", "efficiency", "reliability", "safety"].map(c => (
            <button key={c} onClick={() => setCat(c)}
                    className={`rounded border px-2 py-1 ${cat === c ? "border-accent text-accent" : "border-line text-muted hover:text-text"}`}>
              {c || "all"}
            </button>
          ))}
        </div>
      </div>
      <section className="card">
        {!q.data ? <Loading state={q} /> : (
          <table className="tbl">
            <thead><tr><th>Cat</th><th>Target</th><th>Description</th><th>Evidence</th><th>Applied</th><th>Created</th></tr></thead>
            <tbody>
              {q.data.map(i => (
                <tr key={i.id}>
                  <td><span className={`badge ${i.category === "quality" ? "badge-info" : i.category === "efficiency" ? "badge-good" : "badge-warn"}`}>{i.category}</span></td>
                  <td className="font-mono text-muted text-xs">{i.target_component}</td>
                  <td className="text-xs">{i.description}</td>
                  <td>{i.evidence_count}</td>
                  <td>{i.applied ? <span className="badge badge-good">✓</span> : <span className="text-muted text-xs">pending</span>}</td>
                  <td className="text-xs text-muted">{fmtDate(i.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
