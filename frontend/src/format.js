export const REASON_LABEL = {
  clinical_urgent: "Clinical",
  medical_advice: "Medical advice",
  not_authorised: "Not authorised",
  ambiguous_patient: "Ambiguous patient",
  out_of_scope: "Out of scope",
};
export const REASON_TONE = {
  clinical_urgent: "red", medical_advice: "red", not_authorised: "amber", ambiguous_patient: "amber", out_of_scope: "slate",
};

export function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}
export function formatDateTime(iso) {
  const d = new Date(iso);
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}, ${formatTime(iso)}`;
}

// `search_slots(doctor_id="dr_rao", date="2026-10-03")` exactly like the brief's mock-up.
export function callSignature(tool) {
  const args = Object.entries(tool.arguments || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`);
  return `${tool.name}(${args.join(", ")})`;
}

// One line saying what the tool layer actually returned: the visual proof of grounding.
export function resultLine(tool) {
  const r = tool.result || {};
  if (r.ok === false) return `→ error ${r.error?.code}: ${r.error?.message}`;
  switch (tool.name) {
    case "search_slots":
      if (r.closed_reason) return `→ 0 slots (${r.closed_reason.replaceAll("_", " ")})`;
      return `→ ${r.count} slot${r.count === 1 ? "" : "s"}${r.count ? `: ${r.slots.slice(0, 6).join(", ")}${r.count > 6 ? ", …" : ""}` : ""}`;
    case "lookup_patient":
      if (r.match === "unique") return `→ unique: ${r.candidates[0].patient_id} ${r.candidates[0].name}`;
      if (r.match === "ambiguous") return `→ ambiguous: ${r.candidates.length} candidates (${r.candidates.map((c) => c.patient_id).join(", ")})`;
      return "→ no match";
    case "book_appointment":
      return `→ booked ${r.appointment.appointment_id} · ${r.appointment.date} ${r.appointment.start}`;
    case "reschedule_appointment":
      return `→ moved ${r.appointment.appointment_id} · ${r.previous.date} ${r.previous.start} → ${r.appointment.date} ${r.appointment.start}`;
    case "cancel_appointment":
      return `→ cancelled ${r.appointment.appointment_id}`;
    case "escalate_to_human":
      return `→ handoff ${r.handoff_id} opened`;
    default:
      return "→ ok";
  }
}

export function stateBadge(response) {
  const s = response.terminal_state;
  if (s === "escalated") return { text: `Escalated — ${(REASON_LABEL[response.escalation_reason] || "").toUpperCase()}`, tone: REASON_TONE[response.escalation_reason] };
  const tone = { booked: "green", rescheduled: "green", cancelled: "green", refused: "slate", abandoned: "slate" }[s];
  return { text: s.toUpperCase(), tone };
}

export function outcomeNote(response) {
  const s = response.terminal_state;
  if (s === "escalated" && response.escalation_reason === "clinical_urgent") return { tone: "red", text: "Booking flow abandoned. No appointment was created." };
  if (s === "escalated") return { tone: "amber", text: "Handed to a human. The agent took no action on any record." };
  if (s === "refused") return { tone: "slate", text: "Refused. Nothing for a human to pick up." };
  if (s === "abandoned") return { tone: "slate", text: "No action taken. Nothing was changed." };
  return { tone: "green", text: `${s[0].toUpperCase()}${s.slice(1)} — ${response.appointment_id}.` };
}
