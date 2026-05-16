import { useState } from "react";
import { api } from "@/lib/api";

export default function Console() {
  const [target, setTarget] = useState("");
  const [pir, setPir] = useState("");
  const [passive, setPassive] = useState(true);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [resp, setResp] = useState<any>(null);
  const [err, setErr] = useState("");

  async function submit() {
    setErr(""); setResp(null); setSubmitting(true);
    try {
      const r = await api<any>("/api/console/dossier", {
        method: "POST",
        body: JSON.stringify({
          target: target.trim(), pir: pir.trim(),
          constraints: { passive_only: passive },
          operator_notes: notes,
        }),
      });
      setResp(r);
    } catch (e: any) {
      setErr(e.message || String(e));
    } finally { setSubmitting(false); }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Console</h1>
      <p className="text-sm text-muted">
        Submit a PIR. The agent loop (Phase B) runs in the background; watch the Runs page for live traces and the Dossiers page for the result.
      </p>

      <section className="card max-w-3xl">
        <div className="space-y-3">
          <Field label="Target (handle / email / domain / name)">
            <input value={target} onChange={e => setTarget(e.target.value)} placeholder="alice123"
                   className="w-full rounded border border-line bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" />
          </Field>
          <Field label="PIR — Priority Intelligence Requirement">
            <textarea value={pir} onChange={e => setPir(e.target.value)} rows={4}
                      placeholder="What do you want to know about this target?"
                      className="w-full rounded border border-line bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" />
          </Field>
          <Field label="Operator notes (optional)">
            <input value={notes} onChange={e => setNotes(e.target.value)}
                   className="w-full rounded border border-line bg-bg px-3 py-2 text-sm focus:border-accent focus:outline-none" />
          </Field>
          <label className="flex items-center gap-2 text-sm text-muted">
            <input type="checkbox" checked={passive} onChange={e => setPassive(e.target.checked)} />
            passive_only (no active scans)
          </label>
          <button onClick={submit} disabled={submitting || !target.trim() || !pir.trim()}
                  className="rounded bg-accent px-4 py-2 text-sm font-semibold text-bg hover:bg-accent/80 disabled:opacity-50">
            {submitting ? "submitting…" : "Submit dossier"}
          </button>
        </div>
      </section>

      {resp && (
        <section className="card max-w-3xl">
          <header className="card-header">Accepted</header>
          <pre className="text-xs whitespace-pre-wrap text-good">{JSON.stringify(resp, null, 2)}</pre>
        </section>
      )}
      {err && (
        <section className="card max-w-3xl">
          <header className="card-header">Error</header>
          <pre className="text-xs whitespace-pre-wrap text-bad">{err}</pre>
        </section>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: any }) {
  return <div><label className="block mb-1 text-[10px] uppercase tracking-wider text-muted">{label}</label>{children}</div>;
}
