"""The six tools. This layer never calls an LLM and never reads the system clock.

It is the ground truth: the agent may only state what these functions returned.
Every tool validates its arguments and fails with a *specific, actionable* error
(``{"ok": false, "error": {"code", "message", "field", "hint"}}``), never a stack trace.
Authorisation lives here too, not only in the agent, so a confused or manipulated
model cannot cancel someone else's appointment even if it tries.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Optional

from .clinic import Clinic, SlotTaken, to_hhmm, to_minutes
from .matching import name_matches, normalise_phone

ESCALATION_REASONS = ("clinical_urgent", "medical_advice", "not_authorised", "ambiguous_patient", "out_of_scope")
WINDOWS = {"morning": (0, 12 * 60), "afternoon": (12 * 60, 16 * 60), "evening": (16 * 60, 24 * 60)}
MAX_DAYS_AHEAD = 180
MAX_TEXT = 500

# name -> {argument: (type, required)}
SPECS: dict[str, dict[str, tuple[type, bool]]] = {
    "search_slots": {"doctor_id": (str, True), "date": (str, True), "window": (str, False)},
    "book_appointment": {
        "patient_id": (str, True), "doctor_id": (str, True), "date": (str, True), "start": (str, True),
        "booked_by": (str, False),
    },
    "reschedule_appointment": {
        "appointment_id": (str, True), "new_date": (str, True), "new_start": (str, True),
        "actor_patient_id": (str, True), "new_doctor_id": (str, False),
    },
    "cancel_appointment": {"appointment_id": (str, True), "actor_patient_id": (str, True)},
    "lookup_patient": {
        "name": (str, False), "phone": (str, False), "dob": (str, False), "ward_of": (str, False),
    },
    "escalate_to_human": {
        "reason": (str, True), "detail": (str, False), "patient_id": (str, False), "caller_said": (str, False),
    },
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, field: Optional[str] = None, hint: Optional[str] = None, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.field, self.hint, self.extra = code, message, field, hint, extra

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.field:
            body["field"] = self.field
        if self.hint:
            body["hint"] = self.hint
        body.update(self.extra)
        return {"ok": False, "error": body}


class ToolLayer:
    def __init__(self, clinic: Clinic):
        self.clinic = clinic
        self._tools: dict[str, Callable[..., dict[str, Any]]] = {
            "search_slots": self.search_slots,
            "book_appointment": self.book_appointment,
            "reschedule_appointment": self.reschedule_appointment,
            "cancel_appointment": self.cancel_appointment,
            "lookup_patient": self.lookup_patient,
            "escalate_to_human": self.escalate_to_human,
        }

    # ------------------------------------------------------------- dispatch
    def call(self, name: Any, arguments: Any) -> dict[str, Any]:
        """Validate and run a tool. Never raises: bad input becomes an ``ok: false`` result."""
        try:
            if not isinstance(name, str) or name not in self._tools:
                raise ToolError(
                    "UNKNOWN_TOOL", f"No tool named {name!r}.", field="name",
                    hint=f"Available tools: {', '.join(sorted(self._tools))}.",
                )
            if not isinstance(arguments, dict):
                raise ToolError("INVALID_ARGUMENTS", "Tool arguments must be a JSON object.", field="arguments")
            self._validate_shape(name, arguments)
            return self._tools[name](**arguments)
        except ToolError as error:
            return error.as_dict()

    @staticmethod
    def _validate_shape(name: str, arguments: dict[str, Any]) -> None:
        spec = SPECS[name]
        unknown = sorted(set(arguments) - set(spec))
        if unknown:
            raise ToolError(
                "UNKNOWN_ARGUMENT", f"{name} does not accept: {', '.join(unknown)}.", field=unknown[0],
                hint=f"Accepted arguments: {', '.join(spec)}.",
            )
        for argument, (kind, required) in spec.items():
            value = arguments.get(argument)
            if value is None:
                if required:
                    raise ToolError("MISSING_ARGUMENT", f"{name} requires '{argument}'.", field=argument)
                continue
            if not isinstance(value, kind):
                raise ToolError(
                    "INVALID_TYPE", f"'{argument}' must be a {kind.__name__}, got {type(value).__name__}.",
                    field=argument,
                )
            if isinstance(value, str) and len(value) > MAX_TEXT:
                raise ToolError("VALUE_TOO_LONG", f"'{argument}' is longer than {MAX_TEXT} characters.", field=argument)

    # ------------------------------------------------------------- argument parsing
    def _doctor(self, doctor_id: str, field: str = "doctor_id") -> dict[str, Any]:
        doctor = self.clinic.doctor(doctor_id)
        if not doctor:
            known = ", ".join(d["id"] for d in self.clinic.doctors())
            raise ToolError("UNKNOWN_DOCTOR", f"No doctor with id '{doctor_id}'.", field=field, hint=f"Known doctors: {known}.")
        return doctor

    def _patient(self, patient_id: str, field: str = "patient_id") -> dict[str, Any]:
        patient = self.clinic.patient(patient_id)
        if not patient:
            raise ToolError(
                "UNKNOWN_PATIENT", f"No patient with id '{patient_id}'.", field=field,
                hint="Resolve the caller with lookup_patient first; never invent an id.",
            )
        return patient

    def _date(self, raw: str, field: str = "date") -> dt.date:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            raise ToolError("INVALID_DATE", f"'{raw}' is not a YYYY-MM-DD date.", field=field, hint="Example: 2026-10-03.")
        try:
            date = dt.date.fromisoformat(raw)
        except ValueError:
            raise ToolError("INVALID_DATE", f"'{raw}' is not a real calendar date.", field=field) from None
        today = self.clinic.today
        if date < today:
            raise ToolError("DATE_IN_PAST", f"{raw} is before today ({today.isoformat()}).", field=field)
        if (date - today).days > MAX_DAYS_AHEAD:
            raise ToolError("DATE_TOO_FAR", f"{raw} is more than {MAX_DAYS_AHEAD} days ahead.", field=field)
        return date

    def _start(self, raw: str, field: str = "start") -> int:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", raw):
            raise ToolError("INVALID_TIME", f"'{raw}' is not a 24-hour HH:MM time.", field=field, hint="Example: 09:30.")
        minutes = to_minutes(raw)
        if minutes % self.clinic.slot_minutes:
            raise ToolError(
                "INVALID_TIME", f"{raw} is not on a {self.clinic.slot_minutes}-minute slot boundary.", field=field,
                hint=f"Slots start every {self.clinic.slot_minutes} minutes, e.g. 09:00, 09:15, 09:30.",
            )
        return minutes

    # ------------------------------------------------------------- shared checks
    def _require_bookable(self, doctor_id: str, date: dt.date, start: int, field_prefix: str = "") -> None:
        """Raise a specific error unless ``doctor_id`` has a free slot at ``date start``."""
        date_field, start_field = (f"{field_prefix}date", f"{field_prefix}start")
        reason = self.clinic.closed_reason(doctor_id, date)
        if reason == "clinic_holiday":
            raise ToolError("CLINIC_CLOSED", f"The clinic is closed on {date.isoformat()} (holiday).", field=date_field)
        if reason == "doctor_on_leave":
            raise ToolError("DOCTOR_ON_LEAVE", f"This doctor is on leave on {date.isoformat()}.", field=date_field)
        if reason == "no_clinic_hours":
            raise ToolError("NO_CLINIC_HOURS", f"This doctor has no clinic hours on {date.strftime('%A')}.", field=date_field)
        if start not in self.clinic.possible_starts(doctor_id, date):
            raise ToolError(
                "NOT_A_SLOT", f"{to_hhmm(start)} is outside this doctor's hours on {date.isoformat()}.", field=start_field,
                hint="Call search_slots to see the real slots.",
            )
        if start in self.clinic.booked_starts(doctor_id, date):
            raise self._slot_taken(doctor_id, date, start, start_field)

    def _slot_taken(self, doctor_id: str, date: dt.date, start: int, field: str) -> ToolError:
        alternatives = [to_hhmm(s) for s in self.clinic.free_starts(doctor_id, date) if s != start][:3]
        return ToolError(
            "SLOT_TAKEN", f"{to_hhmm(start)} on {date.isoformat()} is already booked.", field=field,
            hint="Offer the caller a different slot from search_slots.", alternatives=alternatives,
        )

    def _require_authorised(self, actor_id: str, patient_id: str, actor_field: str) -> None:
        self._patient(actor_id, actor_field)
        if not self.clinic.is_authorised(actor_id, patient_id):
            raise ToolError(
                "NOT_AUTHORISED",
                f"{actor_id} is neither {patient_id} nor a listed guardian of {patient_id}.",
                field=actor_field,
                hint="Do not act. Escalate with reason 'not_authorised'.",
            )

    def _appointment_view(self, appointment: dict[str, Any]) -> dict[str, Any]:
        doctor = self.clinic.doctor(appointment["doctor_id"]) or {}
        return {
            "appointment_id": appointment["id"], "patient_id": appointment["patient_id"],
            "doctor_id": appointment["doctor_id"], "doctor_name": doctor.get("name"),
            "date": appointment["date"], "start": appointment["start"], "end": appointment["end"],
            "status": appointment["status"],
        }

    # =================================================================== tools
    def search_slots(self, doctor_id: str, date: str, window: Optional[str] = None) -> dict[str, Any]:
        doctor = self._doctor(doctor_id)
        day = self._date(date)
        if window is not None and window not in WINDOWS:
            raise ToolError("INVALID_WINDOW", f"'{window}' is not a window.", field="window", hint="Use morning, afternoon or evening.")
        closed = self.clinic.closed_reason(doctor_id, day)
        starts = self.clinic.free_starts(doctor_id, day)
        if window:
            low, high = WINDOWS[window]
            starts = [s for s in starts if low <= s < high]
        return {
            "ok": True, "doctor_id": doctor_id, "doctor_name": doctor["name"], "date": day.isoformat(),
            "weekday": day.strftime("%A"), "window": window, "closed_reason": closed,
            "slots": [to_hhmm(s) for s in starts], "count": len(starts),
        }

    def book_appointment(
        self, patient_id: str, doctor_id: str, date: str, start: str, booked_by: Optional[str] = None
    ) -> dict[str, Any]:
        self._patient(patient_id)
        self._doctor(doctor_id)
        day, minutes = self._date(date), self._start(start)
        actor = booked_by or patient_id
        self._require_authorised(actor, patient_id, "booked_by")
        self._require_bookable(doctor_id, day, minutes)
        if self.clinic.patient_busy_at(patient_id, day, minutes):
            raise ToolError(
                "PATIENT_DOUBLE_BOOKED", f"{patient_id} already has an appointment at {start} on {date}.", field="start",
                hint="Pick a different time.",
            )
        try:
            appointment = self.clinic.insert_appointment(patient_id, doctor_id, day, minutes, actor)
        except SlotTaken:
            raise self._slot_taken(doctor_id, day, minutes, "start") from None
        return {"ok": True, "appointment": self._appointment_view(appointment)}

    def reschedule_appointment(
        self, appointment_id: str, new_date: str, new_start: str, actor_patient_id: str,
        new_doctor_id: Optional[str] = None,
    ) -> dict[str, Any]:
        appointment = self._live_appointment(appointment_id)
        self._require_authorised(actor_patient_id, appointment["patient_id"], "actor_patient_id")
        doctor_id = new_doctor_id or appointment["doctor_id"]
        self._doctor(doctor_id, "new_doctor_id")
        day, minutes = self._date(new_date, "new_date"), self._start(new_start, "new_start")
        if (doctor_id, day.isoformat(), to_hhmm(minutes)) == (appointment["doctor_id"], appointment["date"], appointment["start"]):
            raise ToolError("SAME_SLOT", "The appointment is already at that time.", field="new_start", hint="Choose a different slot.")
        self._require_bookable(doctor_id, day, minutes, field_prefix="new_")
        if self.clinic.patient_busy_at(appointment["patient_id"], day, minutes, ignore_id=appointment_id):
            raise ToolError("PATIENT_DOUBLE_BOOKED", "The patient already has another appointment at that time.", field="new_start")
        previous = self._appointment_view(appointment)
        try:
            moved = self.clinic.move_appointment(appointment_id, doctor_id, day, minutes)
        except SlotTaken:
            raise self._slot_taken(doctor_id, day, minutes, "new_start") from None
        return {"ok": True, "appointment": self._appointment_view(moved), "previous": previous}

    def cancel_appointment(self, appointment_id: str, actor_patient_id: str) -> dict[str, Any]:
        appointment = self._live_appointment(appointment_id)
        self._require_authorised(actor_patient_id, appointment["patient_id"], "actor_patient_id")
        cancelled = self.clinic.set_status(appointment_id, "cancelled")
        return {"ok": True, "appointment": self._appointment_view(cancelled)}

    def _live_appointment(self, appointment_id: str) -> dict[str, Any]:
        appointment = self.clinic.appointment(appointment_id)
        if not appointment:
            raise ToolError(
                "UNKNOWN_APPOINTMENT", f"No appointment with id '{appointment_id}'.", field="appointment_id",
                hint="Use an id returned by lookup_patient; never invent one.",
            )
        if appointment["status"] != "booked":
            raise ToolError("ALREADY_CANCELLED", f"{appointment_id} is already cancelled.", field="appointment_id")
        return appointment

    def lookup_patient(
        self, name: Optional[str] = None, phone: Optional[str] = None, dob: Optional[str] = None,
        ward_of: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return *candidates*. ``match`` says whether the evidence singled one out; we never pick for you."""
        if not (name and name.strip()) and not phone and not dob and not ward_of:
            raise ToolError("MISSING_ARGUMENT", "Provide at least one of name, phone, dob or ward_of.", field="name")
        digits = None
        if phone:
            digits = normalise_phone(phone)
            if digits is None:
                raise ToolError("INVALID_PHONE", f"'{phone}' is not a 10-digit mobile number.", field="phone", hint="Example: 9812200311.")
        if dob and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dob):
            raise ToolError("INVALID_DATE", f"'{dob}' is not a YYYY-MM-DD date of birth.", field="dob")
        pool = self.clinic.patients()
        if ward_of is not None:
            self._patient(ward_of, "ward_of")
            wards = set(self.clinic.wards_of(ward_of))
            pool = [p for p in pool if p["id"] in wards]
        candidates = [
            p for p in pool
            if (digits is None or p["phone"] == digits)
            and (dob is None or p["dob"] == dob)
            and (not name or name_matches(name, p["name"]))
        ]
        result: dict[str, Any] = {
            "ok": True,
            "match": "none" if not candidates else "unique" if len(candidates) == 1 else "ambiguous",
            "candidates": [
                {"patient_id": p["id"], "name": p["name"], "dob": p["dob"], "guardian_of": self.clinic.wards_of(p["id"])}
                for p in candidates
            ],
        }
        if len(candidates) == 1:  # appointments are only revealed once the identity is unambiguous
            result["upcoming_appointments"] = [
                self._appointment_view(a) for a in self.clinic.appointments_for(candidates[0]["id"])
                if a["date"] >= self.clinic.today.isoformat()
            ]
        return result

    def escalate_to_human(
        self, reason: str, detail: Optional[str] = None, patient_id: Optional[str] = None,
        caller_said: Optional[str] = None,
    ) -> dict[str, Any]:
        if reason not in ESCALATION_REASONS:
            raise ToolError(
                "INVALID_REASON", f"'{reason}' is not an escalation reason.", field="reason",
                hint=f"Use one of: {', '.join(ESCALATION_REASONS)}.",
            )
        if patient_id is not None:
            self._patient(patient_id)
        record = self.clinic.add_escalation(
            {"reason": reason, "detail": detail, "patient_id": patient_id, "caller_said": caller_said}
        )
        return {"ok": True, "handoff_id": record["handoff_id"], "status": "open", "reason": reason}
