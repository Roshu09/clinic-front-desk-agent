# Sunrise Clinic — Front Desk Agent

A Python REST API with a conversational agent over six tools, plus a React dashboard (Handoff Queue + Conversation Detail).
The design goal is an agent that stays **safe, predictable and honest when the model is free to do anything**: the model only *reads* the caller; code decides; replies come from tool results.

* **Live link:** _<paste your deployed URL here>_ (API at `/agent/run`, dashboard at `/`)
* **Read first:** [`DECISIONS.md`](DECISIONS.md) — every ambiguity, what I chose, and what looks wrong in the starter pack.

## Run it (one command)

```bash
./run.sh                       # installs deps, builds the UI, serves API + dashboard on http://localhost:8000
```

No API key is needed. Without one the agent runs on its deterministic rules engine, offline. With any OpenAI-compatible endpoint the LLM layer is switched on:

```bash
LLM_API_KEY=sk-... LLM_BASE_URL=https://api.groq.com/openai/v1 LLM_MODEL=llama-3.3-70b-versatile ./run.sh
# Gemini:  LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai  LLM_MODEL=gemini-2.0-flash
# OpenAI:  LLM_BASE_URL=https://api.openai.com/v1                                LLM_MODEL=gpt-4o-mini
```

Docker instead: `docker build -t frontdesk . && docker run -p 8000:8000 frontdesk`. Windows without bash: run the two steps in `run.sh` by hand.

### Check it

```bash
cd backend && python3 -m pytest -q                         # 117 tests: tool layer, race, agent, malformed LLM, API
python3 scripts/check.py                                   # all 15 starter + 8 adversarial scripts vs their `expected` blocks
cd ../starter && python3 runner.py --repeat 3              # official runner, determinism check (server must be running)
python3 runner.py --dir ../adversarial --repeat 3          # my 8 adversarial cases through the same runner
```

## Architecture

```
caller turns ──► rules NLU ──┐                                   ┌─► templated reply (tool results only)
                             ├─► facts ─► deterministic planner ─┤
(optional) LLM extractor ────┘   validated, grounded,            └─► tool layer ─► in-memory SQLite (from clinic.json)
 may only fill gaps / add         safety flags OR-ed                  never calls an LLM; re-checks auth + slots
 safety flags                                                         unique index forbids double-booking
```

| File | Role |
|---|---|
| `backend/app/tools.py` | The six tools. Validation, specific errors, authorisation. **No LLM, no clock.** |
| `backend/app/clinic.py` | Data store + scheduling rules (windows, leave, holidays, partial unique index, lock). |
| `backend/app/matching.py` | Deterministic name/phone matching that widens candidates, never guesses. |
| `backend/app/dates.py` | Hindi/English/Hinglish dates and clock times against the request's `today`. |
| `backend/app/safety.py` | Emergency, medical-advice, out-of-scope, injection and bulk detectors. Always run. |
| `backend/app/nlu_rules.py` / `nlu_llm.py` | Turn → structured facts (rules; optional validated LLM). |
| `backend/app/agent.py` | The conversation state machine and every decision. |
| `backend/app/replies.py` | Reply templates. Facts are passed in from tool results only. |
| `backend/app/main.py`, `store.py` | REST API and the dashboard's audit log. |
| `frontend/` | React (Vite): Handoff Queue, Conversation Detail, shared sidebar. |
| `adversarial/` | 8 scripts that break a naive agent, each with a `notes` line saying why. |

## API contract

### `POST /agent/run` (the graded endpoint; exactly `starter/schema.md`)

```jsonc
// request
{ "conversation_id": "cv_0001", "today": "2026-10-01", "turns": ["Namaste, Dr. Rao ke saath appointment chahiye tha.", "..."] }
// response 200
{ "conversation_id": "cv_0001",
  "tool_calls": [{"name": "lookup_patient", "arguments": {"name": "Harpreet Singh", "phone": "9812200311"}}, ...],
  "terminal_state": "booked",            // booked | rescheduled | cancelled | escalated | refused | abandoned
  "escalation_reason": null,              // clinical_urgent | medical_advice | not_authorised | ambiguous_patient | out_of_scope (only when escalated)
  "patient_id": "pt_0013", "appointment_id": "ap_0026",
  "reply": "Ji, 3 October (Saturday) ko 09:00 baje Dr. Anjali Rao ke saath appointment book ho gaya hai. ...",
  "metrics": {"turns": 3, "tokens": 0, "latency_ms": 4} }
```
Bad requests return **422** `{"detail": {"code": "INVALID_REQUEST", "field": "today", "message": "today must be YYYY-MM-DD."}}`, never a 500. If the agent itself throws, the run still returns a valid result: a deterministic emergency scan runs first, otherwise it escalates `out_of_scope`.

### Tools (`POST /tools/{name}` runs one against a fresh clinic)

| Tool | Arguments | Returns / notable errors |
|---|---|---|
| `search_slots` | `doctor_id`, `date`, `window?` (morning/afternoon/evening) | `slots[]`, `count`, `closed_reason` (clinic_holiday, doctor_on_leave, no_clinic_hours) |
| `book_appointment` | `patient_id`, `doctor_id`, `date`, `start`, `booked_by?` | `appointment`; `SLOT_TAKEN` (+ `alternatives`), `NOT_AUTHORISED`, `DOCTOR_ON_LEAVE`, `CLINIC_CLOSED`, `NOT_A_SLOT`, `PATIENT_DOUBLE_BOOKED` |
| `reschedule_appointment` | `appointment_id`, `new_date`, `new_start`, `actor_patient_id`, `new_doctor_id?` | `appointment` + `previous`; `SAME_SLOT`, `SLOT_TAKEN`, `NOT_AUTHORISED` |
| `cancel_appointment` | `appointment_id`, `actor_patient_id` | `appointment`; `ALREADY_CANCELLED`, `NOT_AUTHORISED` |
| `lookup_patient` | `name?`, `phone?`, `dob?`, `ward_of?` (≥1) | `match`: `unique` / `ambiguous` / `none` + `candidates[]` (never picks one). `upcoming_appointments` only when unique |
| `escalate_to_human` | `reason`, `detail?`, `patient_id?`, `caller_said?` | `handoff_id`, `status: open` |

Every failure is `{"ok": false, "error": {"code", "message", "field", "hint"}}`: e.g. `INVALID_DATE: '3rd October' is not a YYYY-MM-DD date.`

### Dashboard API

`GET /api/summary` · `GET /api/handoffs` · `GET /api/conversations` · `GET /api/conversations/{id}` (transcript with tool calls inline, outcome, stability) · `POST /api/conversations/{id}/rerun` · `POST /api/handoffs/{id}/resolve` · `POST /api/demo/seed` · `GET /health`.
On first start the dashboard is seeded by replaying the bundled scripts (`SEED_DEMO=0` disables).

## Model, tokens and latency

* **Model:** `openai/gpt-oss-120b` via Groq (OpenAI-compatible endpoint, temperature 0, reasoning effort low). The LLM only extracts structured facts; it never writes to the caller.
* Reproduce the table with your key: `cd backend && LLM_API_KEY=… LLM_BASE_URL=… LLM_MODEL=… LLM_CACHE=0 python3 scripts/benchmark.py` (writes `BENCHMARK.md`; paste it here).
* **Rules-only mode (no key), measured:** 0 tokens; mean 3 ms, max 11 ms per conversation across the 23 bundled scripts (in-process, `python3 scripts/benchmark.py` with no key).

**LLM mode, measured** (23 bundled scripts, cold calls, `LLM_CACHE=0`; latency includes Groq free-tier rate-limit waits):

Model: `openai/gpt-oss-120b`

| conversation | turns | terminal_state | tokens | latency (ms) |
|---|---|---|---|---|
| adv_0001 | 2 | escalated | 1157 | 2485 |
| adv_0002 | 2 | booked | 1205 | 1896 |
| adv_0003 | 3 | escalated | 1010 | 1854 |
| adv_0004 | 2 | escalated | 1052 | 1116 |
| adv_0005 | 3 | booked | 1267 | 1801 |
| adv_0006 | 2 | abandoned | 1100 | 2801 |
| adv_0007 | 3 | abandoned | 1033 | 1126 |
| adv_0008 | 2 | escalated | 1068 | 2162 |
| cv_0001 | 3 | booked | 972 | 999 |
| cv_0002 | 3 | booked | 1184 | 1094 |
| cv_0003 | 3 | rescheduled | 1229 | 2296 |
| cv_0004 | 2 | cancelled | 1036 | 5122 |
| cv_0005 | 3 | abandoned | 1228 | 7983 |
| cv_0006 | 3 | booked | 1311 | 6760 |
| cv_0007 | 3 | escalated | 1272 | 5323 |
| cv_0008 | 3 | booked | 1229 | 5120 |
| cv_0009 | 3 | escalated | 1264 | 9214 |
| cv_0010 | 3 | escalated | 1176 | 6552 |
| cv_0011 | 3 | escalated | 1204 | 3993 |
| cv_0012 | 2 | booked | 1118 | 9012 |
| cv_0013 | 3 | abandoned | 859 | 2864 |
| cv_0014 | 3 | refused | 1244 | 5221 |
| cv_0015 | 3 | booked | 1245 | 8399 |

**Mean:** 1151 tokens, 4139 ms per conversation (median 2864 ms, max 9214 ms) over 23 conversations.

NLU mode seen: llm:openai/gpt-oss-120b + rules

## How data stays consistent on update

Each `/agent/run` builds a private in-memory SQLite copy of `clinic.json`, so conversations never leak into each other. Inside it, every write is `BEGIN IMMEDIATE` under a lock, and a partial unique index on `(doctor_id, date, start) WHERE status='booked'` makes a second live booking at the same slot impossible. Reschedule is an in-place update (same appointment id) that is validated first and rolled back on failure. The race test starts 30 threads on one slot and expects exactly one winner.

## What I would do with four more hours

See the email. Short version: a real Devanagari name matcher, a confirmation step for destructive actions, and an eval set of ~100 paraphrased emergencies to measure the recall/restraint trade-off instead of reasoning about it.
