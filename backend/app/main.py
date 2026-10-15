"""REST API.

  POST /agent/run                    the graded endpoint (schema.md)
  POST /tools/{name}                 call one tool directly against a fresh clinic (debugging / docs)
  GET  /api/summary                  handoff-queue counters
  GET  /api/handoffs                 open (and resolved) handoffs, newest first
  GET  /api/conversations            latest run per conversation
  GET  /api/conversations/{id}       transcript with inline tool calls + outcome + stability
  POST /api/handoffs/{id}/resolve    mark a handoff resolved
  POST /api/demo/seed                replay the bundled example conversations into the dashboard
  GET  /health
The built React app, if present, is served from / so one process serves everything.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .agent import FrontDeskAgent
from .clinic import Clinic
from .service import build_extractor
from .store import make_store
from .tools import SPECS, ToolLayer

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"
SEED_DIRS = [ROOT / "starter" / "conversations", ROOT / "adversarial"]

app = FastAPI(title="Sunrise Clinic Front Desk Agent", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
agent = FrontDeskAgent(extractor=build_extractor())
store = make_store()


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    first = error.errors()[0] if error.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", [])[1:]) or "body"
    return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "field": where,
                                                            "message": first.get("msg", "invalid request")}})


def _validated(payload: Any) -> tuple[str, str, list[str]]:
    """Specific, actionable errors for a bad /agent/run body instead of a 500."""
    if not isinstance(payload, dict):
        raise HTTPException(422, {"code": "INVALID_REQUEST", "message": "Body must be a JSON object."})
    cid, today, turns = payload.get("conversation_id"), payload.get("today", "2026-10-01"), payload.get("turns")
    if not isinstance(cid, str) or not cid:
        raise HTTPException(422, {"code": "INVALID_REQUEST", "field": "conversation_id", "message": "conversation_id must be a non-empty string."})
    if not isinstance(today, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", today):
        raise HTTPException(422, {"code": "INVALID_REQUEST", "field": "today", "message": "today must be YYYY-MM-DD."})
    try:
        dt.date.fromisoformat(today)
    except ValueError:
        raise HTTPException(422, {"code": "INVALID_REQUEST", "field": "today", "message": f"{today} is not a real date."}) from None
    if not isinstance(turns, list) or not all(isinstance(t, str) for t in turns) or len(turns) > 50:
        raise HTTPException(422, {"code": "INVALID_REQUEST", "field": "turns", "message": "turns must be a list of at most 50 strings."})
    return cid, today, [t[:2000] for t in turns]


@app.post("/agent/run")
async def agent_run(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(422, {"code": "INVALID_REQUEST", "message": "Body is not valid JSON."}) from None
    cid, today, turns = _validated(payload)
    result = await run_in_threadpool(agent.run, cid, today, turns)
    store.add(result)
    return result.to_response()


@app.post("/tools/{name}")
def call_tool(name: str, arguments: dict, today: str = "2026-10-01"):
    """Run one tool against a pristine clinic. Useful for poking the tool layer without the agent."""
    if name not in SPECS:
        raise HTTPException(404, {"code": "UNKNOWN_TOOL", "message": f"No tool named {name!r}.", "hint": f"Available: {', '.join(SPECS)}."})
    result = ToolLayer(Clinic(today=today)).call(name, arguments)
    return JSONResponse(status_code=200 if result.get("ok") else 422, content=result)


@app.get("/health")
def health():
    return {"ok": True, "nlu": "llm+rules" if agent.extractor else "rules"}


@app.get("/api/summary")
def summary():
    return store.summary()


@app.get("/api/handoffs")
def handoffs():
    rows = [r for r in store.latest_per_conversation() if r["response"]["terminal_state"] == "escalated"]
    return [{
        "conversation_id": r["conversation_id"], "caller_said": _caller_said(r), "reason": r["response"]["escalation_reason"],
        "created_at": r["created_at"], "status": r["handoff_status"], "patient_id": r["response"]["patient_id"],
    } for r in rows]


def _caller_said(record: dict[str, Any]) -> str:
    handoff = next((e["tool"] for e in record["events"] if e["tool"] and e["tool"]["name"] == "escalate_to_human"), None)
    said = (handoff or {}).get("arguments", {}).get("caller_said")
    return said or next((e["text"] for e in reversed(record["events"]) if e["kind"] == "caller"), "")


@app.get("/api/conversations")
def conversations():
    return [{
        "conversation_id": r["conversation_id"], "terminal_state": r["response"]["terminal_state"],
        "escalation_reason": r["response"]["escalation_reason"], "created_at": r["created_at"],
    } for r in store.latest_per_conversation()]


@app.get("/api/conversations/{conversation_id}")
def conversation(conversation_id: str):
    runs = store.runs_for(conversation_id)
    if not runs:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": f"No stored run for {conversation_id}."})
    return {**runs[0], "stability": store.stability(conversation_id)}


@app.post("/api/conversations/{conversation_id}/rerun")
def rerun(conversation_id: str, times: int = 3):
    """Replay the stored script N times (determinism check shown in the outcome panel)."""
    runs = store.runs_for(conversation_id)
    if not runs:
        raise HTTPException(404, {"code": "NOT_FOUND", "message": f"No stored run for {conversation_id}."})
    base = runs[0]
    for _ in range(max(1, min(times, 5))):
        store.add(agent.run(conversation_id, base["today"], base["turns"]))
    return store.stability(conversation_id)


@app.post("/api/handoffs/{conversation_id}/resolve")
def resolve(conversation_id: str):
    if not store.resolve(conversation_id):
        raise HTTPException(404, {"code": "NOT_OPEN", "message": f"No open handoff for {conversation_id}."})
    return {"ok": True}


@app.post("/api/demo/seed")
def seed(reset: bool = True):
    """Replay the bundled example + adversarial scripts so the dashboard has content."""
    if reset:
        store.clear()
    count = 0
    for directory in SEED_DIRS:
        for path in sorted(directory.glob("*.json")):
            script = json.loads(path.read_text(encoding="utf-8"))
            for _ in range(3 if script["id"] == "cv_0011" else 1):  # one case gets the 3-run STABLE badge
                store.add(agent.run(script["id"], script.get("today", "2026-10-01"), script["turns"]))
            count += 1
    return {"seeded": count}


@app.on_event("startup")
def maybe_seed() -> None:
    import os
    if os.environ.get("SEED_DEMO", "1") == "1" and not store.latest_per_conversation():
        seed(reset=False)


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        return FileResponse(candidate if candidate.is_file() else FRONTEND_DIST / "index.html")
