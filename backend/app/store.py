"""Persistence for the dashboard: every /agent/run is stored so the UI can show it.

This is NOT the clinic's ground truth (that is rebuilt from clinic.json per run). It is an
audit log: the transcript with tool calls inline, the machine-readable outcome, and the
state of the human handoff (open / resolved). In-memory by default; SQLite file if
STORE_PATH is set so a restart keeps the queue.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from typing import Any, Optional

from .agent import RunResult

URGENT_REASONS = {"clinical_urgent"}


def _fingerprint(record: dict[str, Any]) -> str:
    names = sorted({c["name"] for c in record["response"]["tool_calls"]})
    return f"{record['response']['terminal_state']}/{record['response']['escalation_reason']}/{','.join(names)}"


class Store:
    def __init__(self, path: Optional[str] = None):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path or ":memory:", check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS runs (seq INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT, created_at TEXT, "
            "handoff_status TEXT, record TEXT)"
        )

    def add(self, result: RunResult) -> dict[str, Any]:
        record = {
            "conversation_id": result.conversation_id,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "today": result.today,
            "turns": result.turns,
            "nlu": result.nlu,
            "response": result.to_response(),
            "events": [
                {"kind": e.kind, "turn": e.turn, "text": e.text,
                 "tool": {"name": e.tool.name, "arguments": e.tool.arguments, "result": e.tool.result} if e.tool else None}
                for e in result.events
            ],
            "handoff": result.handoff,
        }
        status = "open" if result.terminal_state == "escalated" else None
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO runs (conversation_id, created_at, handoff_status, record) VALUES (?,?,?,?)",
                (result.conversation_id, record["created_at"], status, json.dumps(record, ensure_ascii=False)),
            )
            record["run_id"] = cursor.lastrowid
        return record

    def _rows(self, where: str = "", params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(f"SELECT seq, handoff_status, record FROM runs {where} ORDER BY seq DESC", params).fetchall()
        out = []
        for row in rows:
            record = json.loads(row["record"])
            record["run_id"], record["handoff_status"] = row["seq"], row["handoff_status"]
            out.append(record)
        return out

    def latest_per_conversation(self) -> list[dict[str, Any]]:
        seen, latest = set(), []
        for record in self._rows():
            if record["conversation_id"] not in seen:
                seen.add(record["conversation_id"])
                latest.append(record)
        return latest

    def runs_for(self, conversation_id: str) -> list[dict[str, Any]]:
        return self._rows("WHERE conversation_id = ?", (conversation_id,))

    def stability(self, conversation_id: str, window: int = 3) -> dict[str, Any]:
        runs = self.runs_for(conversation_id)[:window]
        prints = {_fingerprint(r) for r in runs}
        return {"runs": len(runs), "stable": len(runs) >= 2 and len(prints) == 1, "fingerprints": sorted(prints)}

    def resolve(self, conversation_id: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "UPDATE runs SET handoff_status='resolved' WHERE seq = (SELECT MAX(seq) FROM runs WHERE conversation_id=?) "
                "AND handoff_status='open'", (conversation_id,))
            return cursor.rowcount > 0

    def summary(self) -> dict[str, Any]:
        latest = self.latest_per_conversation()
        escalated = [r for r in latest if r["response"]["terminal_state"] == "escalated"]
        open_ones = [r for r in escalated if r["handoff_status"] == "open"]
        completed = [r for r in latest if r["response"]["terminal_state"] in ("booked", "rescheduled", "cancelled")]
        total = len(latest)
        return {
            "conversations": total,
            "completed": len(completed),
            "completed_pct": round(100 * len(completed) / total) if total else 0,
            "escalated": len(escalated),
            "escalated_open": len(open_ones),
            "urgent_open": sum(1 for r in open_ones if r["response"]["escalation_reason"] in URGENT_REASONS),
        }

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM runs")


def make_store() -> Store:
    return Store(os.environ.get("STORE_PATH"))
