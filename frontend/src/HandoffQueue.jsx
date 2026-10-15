import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import { REASON_LABEL, REASON_TONE, formatTime } from "./format.js";

function Stat({ label, value, sub, tone }) {
  return (
    <div className="card stat">
      <div className="eyebrow">{label}</div>
      <div className="stat-value">{value}</div>
      <div className={`stat-sub ${tone || ""}`}>{sub}</div>
    </div>
  );
}

export default function HandoffQueue() {
  const [summary, setSummary] = useState(null);
  const [handoffs, setHandoffs] = useState([]);
  const [showResolved, setShowResolved] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([api.summary(), api.handoffs()]);
      setSummary(s);
      setHandoffs(h);
      setError("");
    } catch (e) {
      setError(e.message);
    }
  }, []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [load]);

  const resolve = async (id) => {
    try {
      await api.resolve(id);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };
  const seed = async () => {
    setBusy(true);
    try {
      await api.seed();
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const open = handoffs.filter((h) => h.status === "open");
  const rows = showResolved ? handoffs : open;
  const firstUrgent = open.find((h) => h.reason === "clinical_urgent");

  return (
    <section className="panel">
      <header className="page-head">
        <div>
          <h1>Handoff Queue</h1>
          <p className="muted">Sunrise Clinic, Dehradun — conversations the agent escalated</p>
        </div>
        <span className="pill blue">{open.length} OPEN</span>
      </header>

      {error && <div className="banner" role="alert">Could not reach the API: {error}</div>}

      <div className="stats">
        <Stat label="Conversations" value={summary?.conversations ?? "–"} sub="today" />
        <Stat label="Completed by agent" value={summary?.completed ?? "–"} sub={summary ? `${summary.completed_pct}%` : ""} />
        <Stat label="Escalated" value={summary?.escalated ?? "–"} sub={summary ? `${summary.escalated_open} still open` : ""} tone="blue" />
        <Stat label="Urgent" value={summary?.urgent_open ?? "–"} sub="clinical, unresolved" tone="red" />
      </div>

      <div className="card table-card">
        <div className="table-head">
          <h2>{showResolved ? "All handoffs" : "Open handoffs"}</h2>
          <button className="link" onClick={() => setShowResolved((v) => !v)}>
            {showResolved ? "Show open only" : `Show resolved (${handoffs.length - open.length})`}
          </button>
        </div>
        {rows.length === 0 ? (
          <div className="empty">
            <p>{handoffs.length === 0 ? "No conversations yet. Replay the example calls to fill the queue." : "No open handoffs. Nice."}</p>
            {handoffs.length === 0 && <button className="btn" disabled={busy} onClick={seed}>{busy ? "Replaying…" : "Replay example calls"}</button>}
          </div>
        ) : (
          <table>
            <thead>
              <tr><th>Conversation</th><th>Caller said</th><th>Reason</th><th>Time</th><th /></tr>
            </thead>
            <tbody>
              {rows.map((h) => (
                <tr key={h.conversation_id} className={h.status === "resolved" ? "done" : ""}>
                  <td className="mono"><a href={`#/conversation/${h.conversation_id}`}>{h.conversation_id}</a></td>
                  <td className="said">“{h.caller_said}”</td>
                  <td><span className={`pill ${REASON_TONE[h.reason]}`}>{(REASON_LABEL[h.reason] || h.reason).toUpperCase()}</span></td>
                  <td className="muted">{formatTime(h.created_at)}</td>
                  <td className="actions">
                    {h.status === "open" ? (
                      <button className={`btn ${firstUrgent && h.conversation_id === firstUrgent.conversation_id ? "primary" : ""}`} onClick={() => resolve(h.conversation_id)}>Resolve</button>
                    ) : <span className="muted">Resolved</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
