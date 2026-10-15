"""The clinic's ground truth: an in-memory SQLite database loaded from clinic.json.

Everything the agent is allowed to claim comes from here, via tools.py.
Nothing in this module (or tools.py) ever calls an LLM or reads the system clock:
"today" is injected, because the evaluation harness controls the date.

Concurrency model
-----------------
One SQLite connection per ``Clinic`` guarded by an RLock, and every write runs in
``BEGIN IMMEDIATE``. On top of that a *partial unique index* on
(doctor_id, date, start) WHERE status='booked' makes a double booking impossible
at the storage layer even if the application-level check is wrong or bypassed.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "clinic.json"
DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

SCHEMA = """
CREATE TABLE doctors      (id TEXT PRIMARY KEY, name TEXT NOT NULL, speciality TEXT NOT NULL);
CREATE TABLE windows      (doctor_id TEXT NOT NULL, day TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL);
CREATE TABLE leave        (doctor_id TEXT NOT NULL, date TEXT NOT NULL);
CREATE TABLE holidays     (date TEXT PRIMARY KEY);
CREATE TABLE patients     (id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, dob TEXT NOT NULL);
CREATE TABLE guardianship (guardian_id TEXT NOT NULL, ward_id TEXT NOT NULL, PRIMARY KEY (guardian_id, ward_id));
CREATE TABLE appointments (
    id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, doctor_id TEXT NOT NULL,
    date TEXT NOT NULL, start TEXT NOT NULL, end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('booked','cancelled')),
    booked_by TEXT
);
-- The invariant that matters: one live appointment per doctor per slot.
CREATE UNIQUE INDEX uq_live_slot ON appointments (doctor_id, date, start) WHERE status = 'booked';
"""


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def weekday_name(date: dt.date) -> str:
    return DAY_NAMES[date.weekday()]


def load_clinic_json(path: Path = DATA_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


class SlotTaken(Exception):
    """The slot was free when we looked but is not free at write time."""


class Clinic:
    """A private, resettable copy of the clinic. Build a new one per conversation."""

    def __init__(self, data: Optional[dict[str, Any]] = None, today: Optional[str] = None):
        data = data if data is not None else load_clinic_json()
        self.name: str = data["clinic"]["name"]
        self.slot_minutes: int = int(data["clinic"]["slot_minutes"])
        self.today: dt.date = dt.date.fromisoformat(today or data["clinic"]["reference_date"])
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self.escalations: list[dict[str, Any]] = []
        self._load(data)

    # ------------------------------------------------------- locked read helpers
    def _all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """All reads go through the lock: one sqlite connection must not be used by two threads at once."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        rows = self._all(sql, params)
        return rows[0] if rows else None

    # ------------------------------------------------------------------ loading
    def _load(self, data: dict[str, Any]) -> None:
        c = self._conn
        for doc in data["doctors"]:
            c.execute("INSERT INTO doctors VALUES (?,?,?)", (doc["id"], doc["name"], doc["speciality"]))
            for w in doc["windows"]:
                c.execute("INSERT INTO windows VALUES (?,?,?,?)", (doc["id"], w["day"], w["start"], w["end"]))
            for leave_date in doc.get("leave_dates", []):
                c.execute("INSERT INTO leave VALUES (?,?)", (doc["id"], leave_date))
        for holiday in data.get("holidays", []):
            c.execute("INSERT INTO holidays VALUES (?)", (holiday,))
        for p in data["patients"]:
            c.execute("INSERT INTO patients VALUES (?,?,?,?)", (p["id"], p["name"], p["phone"], p["dob"]))
            for ward in p.get("guardian_of", []):
                c.execute("INSERT INTO guardianship VALUES (?,?)", (p["id"], ward))
        for a in data["appointments"]:
            c.execute(
                "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)",
                (a["id"], a["patient_id"], a["doctor_id"], a["date"], a["start"], a["end"], a["status"], None),
            )

    # --------------------------------------------------------------------- reads
    def doctors(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._all("SELECT * FROM doctors ORDER BY id")]

    def doctor(self, doctor_id: str) -> Optional[dict[str, Any]]:
        row = self._one("SELECT * FROM doctors WHERE id=?", (doctor_id,))
        return dict(row) if row else None

    def patient(self, patient_id: str) -> Optional[dict[str, Any]]:
        row = self._one("SELECT * FROM patients WHERE id=?", (patient_id,))
        return dict(row) if row else None

    def patients(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._all("SELECT * FROM patients ORDER BY id")]

    def wards_of(self, guardian_id: str) -> list[str]:
        rows = self._all(
            "SELECT ward_id FROM guardianship WHERE guardian_id=? ORDER BY ward_id", (guardian_id,)
        )
        return [r["ward_id"] for r in rows]

    def is_authorised(self, actor_id: str, patient_id: str) -> bool:
        """An actor may act on their own record or on a record they are a listed guardian of."""
        return actor_id == patient_id or patient_id in self.wards_of(actor_id)

    def appointment(self, appointment_id: str) -> Optional[dict[str, Any]]:
        row = self._one("SELECT * FROM appointments WHERE id=?", (appointment_id,))
        return dict(row) if row else None

    def appointments_for(self, patient_id: str, only_booked: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM appointments WHERE patient_id=?"
        if only_booked:
            sql += " AND status='booked'"
        sql += " ORDER BY date, start"
        return [dict(r) for r in self._all(sql, (patient_id,))]

    def closed_reason(self, doctor_id: str, date: dt.date) -> Optional[str]:
        """Why a doctor cannot see patients on ``date`` (None if they can)."""
        iso = date.isoformat()
        if self._one("SELECT 1 FROM holidays WHERE date=?", (iso,)):
            return "clinic_holiday"
        if self._one("SELECT 1 FROM leave WHERE doctor_id=? AND date=?", (doctor_id, iso)):
            return "doctor_on_leave"
        has_window = self._one(
            "SELECT 1 FROM windows WHERE doctor_id=? AND day=?", (doctor_id, weekday_name(date))
        )
        if not has_window:
            return "no_clinic_hours"
        return None

    def possible_starts(self, doctor_id: str, date: dt.date) -> list[int]:
        """Every bookable start time (minutes) that day, ignoring existing bookings.

        Windows may overlap in the data (Dr. Rao on Mondays), so slots are a *set*:
        an overlapped slot must not appear twice.
        """
        if self.closed_reason(doctor_id, date):
            return []
        starts: set[int] = set()
        rows = self._all(
            "SELECT start, end FROM windows WHERE doctor_id=? AND day=?", (doctor_id, weekday_name(date))
        )
        for row in rows:
            begin, finish = to_minutes(row["start"]), to_minutes(row["end"])
            t = begin
            while t + self.slot_minutes <= finish:
                starts.add(t)
                t += self.slot_minutes
        return sorted(starts)

    def booked_starts(self, doctor_id: str, date: dt.date) -> set[int]:
        rows = self._all(
            "SELECT start FROM appointments WHERE doctor_id=? AND date=? AND status='booked'",
            (doctor_id, date.isoformat()),
        )
        return {to_minutes(r["start"]) for r in rows}

    def free_starts(self, doctor_id: str, date: dt.date) -> list[int]:
        taken = self.booked_starts(doctor_id, date)
        return [s for s in self.possible_starts(doctor_id, date) if s not in taken]

    def patient_busy_at(self, patient_id: str, date: dt.date, start: int, ignore_id: Optional[str] = None) -> bool:
        rows = self._all(
            "SELECT id, start FROM appointments WHERE patient_id=? AND date=? AND status='booked'",
            (patient_id, date.isoformat()),
        )
        return any(r["id"] != ignore_id and to_minutes(r["start"]) == start for r in rows)

    # -------------------------------------------------------------------- writes
    def _next_appointment_id(self) -> str:
        row = self._one("SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER)) AS n FROM appointments")
        return f"ap_{(row['n'] or 0) + 1:04d}"

    def insert_appointment(
        self, patient_id: str, doctor_id: str, date: dt.date, start: int, booked_by: str
    ) -> dict[str, Any]:
        """Atomically create an appointment. Raises SlotTaken if the slot is not free."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if start not in self.free_starts(doctor_id, date):
                    raise SlotTaken()
                appointment_id = self._next_appointment_id()
                self._conn.execute(
                    "INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?)",
                    (appointment_id, patient_id, doctor_id, date.isoformat(), to_hhmm(start),
                     to_hhmm(start + self.slot_minutes), "booked", booked_by),
                )
                self._conn.execute("COMMIT")
            except sqlite3.IntegrityError as error:  # the unique index is the last line of defence
                self._conn.execute("ROLLBACK")
                raise SlotTaken() from error
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            return self.appointment(appointment_id)  # type: ignore[return-value]

    def move_appointment(
        self, appointment_id: str, doctor_id: str, date: dt.date, start: int
    ) -> dict[str, Any]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if start not in self.free_starts(doctor_id, date):
                    raise SlotTaken()
                self._conn.execute(
                    "UPDATE appointments SET doctor_id=?, date=?, start=?, end=? WHERE id=? AND status='booked'",
                    (doctor_id, date.isoformat(), to_hhmm(start), to_hhmm(start + self.slot_minutes), appointment_id),
                )
                self._conn.execute("COMMIT")
            except sqlite3.IntegrityError as error:
                self._conn.execute("ROLLBACK")
                raise SlotTaken() from error
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            return self.appointment(appointment_id)  # type: ignore[return-value]

    def set_status(self, appointment_id: str, status: str) -> dict[str, Any]:
        with self._lock:
            self._conn.execute("UPDATE appointments SET status=? WHERE id=?", (status, appointment_id))
            return self.appointment(appointment_id)  # type: ignore[return-value]

    def add_escalation(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = {"handoff_id": f"ho_{len(self.escalations) + 1:04d}", "status": "open", **record}
            self.escalations.append(record)
            return record
