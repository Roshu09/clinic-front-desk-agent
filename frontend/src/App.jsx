import React, { useEffect, useState } from "react";
import HandoffQueue from "./HandoffQueue.jsx";
import ConversationDetail from "./ConversationDetail.jsx";
import { api } from "./api.js";

// Hash routing keeps the SPA deployable on any static host with no rewrite rules.
function useRoute() {
  const read = () => window.location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

const NAV = [
  { id: "overview", label: "Overview (not in this prototype)" },
  { id: "calls", label: "Live calls (not in this prototype)" },
  { id: "queue", label: "Handoff queue", href: "#/" },
  { id: "conversations", label: "Latest conversation", latest: true },
  { id: "patients", label: "Patients (not in this prototype)" },
  { id: "schedule", label: "Schedule (not in this prototype)" },
  { id: "settings", label: "Settings (not in this prototype)" },
];

function Sidebar({ route }) {
  const onDetail = route.startsWith("/conversation/");
  const go = async (item) => {
    if (item.href) window.location.hash = item.href;
    if (item.latest) {
      const list = await api.conversations().catch(() => []);
      if (list.length) window.location.hash = `#/conversation/${list[0].conversation_id}`;
    }
  };
  return (
    <nav className="sidebar" aria-label="Main">
      {NAV.map((item) => {
        const enabled = Boolean(item.href || item.latest);
        const active = (item.id === "queue" && !onDetail) || (item.id === "conversations" && onDetail);
        return (
          <button key={item.id} className={`dot${active ? " active" : ""}`} title={item.label} aria-label={item.label}
            aria-current={active ? "page" : undefined} disabled={!enabled} onClick={() => go(item)} />
        );
      })}
    </nav>
  );
}

export default function App() {
  const route = useRoute();
  const match = route.match(/^\/conversation\/(.+)$/);
  return (
    <div className="shell">
      <Sidebar route={route} />
      <main className="content">{match ? <ConversationDetail id={decodeURIComponent(match[1])} /> : <HandoffQueue />}</main>
    </div>
  );
}
