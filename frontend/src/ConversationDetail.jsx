import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { callSignature, formatDateTime, outcomeNote, resultLine, stateBadge } from "./format.js";

const LABEL = { caller: "CALLER", tool: "TOOL", agent: "AGENT" };

function Row({ label, value }) {
  return (
    <div className="kv"><span>{label}</span><span className="mono strong">{value}</span></div>
  );
}

export default function ConversationDetail({ id }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.conversation(id));
      setError("");
    } catch (e) {
      setData(null);
      setError(e.message);
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const rerun = async () => {
    setBusy(true);
    try { await api.rerun(id); await load(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  if (error) return <section className="panel"><a href="#/" className="back">← Handoff queue</a><div className="banner" role="alert">{error}</div></section>;
  if (!data) return <section className="panel"><p className="muted">Loading…</p></section>;

  const r = data.response;
  const badge = stateBadge(r);
  const note = outcomeNote(r);
  const stab = data.stability;
  const tokens = r.metrics.tokens;

  return (
    <section className="panel">
      <a href="#/" className="back">← Handoff queue</a>
      <header className="page-head">
        <div>
          <h1>Conversation {data.conversation_id}</h1>
          <p className="muted">Sunrise Clinic, Dehradun — {formatDateTime(data.created_at)}</p>
        </div>
        <span className={`pill ${badge.tone}`}>{badge.text}</span>
      </header>

      <div className="detail-grid">
        <div className="card">
          <h2>Transcript and tool calls</h2>
          <div className="transcript">
            {data.events.map((e, i) => (
              <div className="line" key={i}>
                <div className="who">{LABEL[e.kind]}</div>
                {e.kind === "tool" ? (
                  <div className="tool">
                    <span className="sig">{callSignature(e.tool)}</span>
                    <div className={`res ${e.tool.result.ok === false ? "bad" : ""}`}>{resultLine(e.tool)}</div>
                  </div>
                ) : (
                  <div className={`bubble ${e.kind}`}>{e.text}</div>
                )}
              </div>
            ))}
            <div className="line"><div className="who" /><div className={`note ${note.tone}`}>{note.text}</div></div>
          </div>
        </div>

        <aside className="card">
          <h2>Outcome</h2>
          <Row label="terminal_state" value={r.terminal_state} />
          <Row label="escalation_reason" value={r.escalation_reason ?? "null"} />
          <Row label="patient_id" value={r.patient_id ?? "null"} />
          <Row label="appointment_id" value={r.appointment_id ?? "null"} />
          <Row label="tool_calls" value={r.tool_calls.length} />
          <Row label="turns" value={r.metrics.turns} />
          <Row label="tokens" value={tokens ? tokens.toLocaleString("en-US") : "0 (rules only)"} />
          <Row label="latency" value={r.metrics.latency_ms >= 1000 ? `${(r.metrics.latency_ms / 1000).toFixed(1)} s` : `${r.metrics.latency_ms} ms`} />
          <div className="eyebrow gap">Determinism</div>
          <div className="det">
            <span className="muted">
              {stab.runs >= 2 ? `Same terminal state across ${stab.runs} runs.` : "Run it again to check determinism."}
            </span>
            {stab.runs >= 2 && <span className={`pill ${stab.stable ? "green" : "red"}`}>{stab.stable ? "STABLE" : "UNSTABLE"}</span>}
          </div>
          <button className="btn" disabled={busy} onClick={rerun}>{busy ? "Re-running…" : "Re-run ×3"}</button>
          <div className="eyebrow gap">Understanding</div>
          <div className="muted small">{data.nlu}</div>
        </aside>
      </div>
    </section>
  );
}
