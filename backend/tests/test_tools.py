"""Tool-layer tests: the ground truth. No LLM anywhere in this file."""
import threading

import pytest

from app.clinic import Clinic
from app.tools import ToolLayer


@pytest.fixture()
def tools():
    return ToolLayer(Clinic(today="2026-10-01"))


def error_code(result):
    assert result["ok"] is False, result
    return result["error"]["code"]


# ---------------------------------------------------------------- search_slots
def test_search_slots_saturday_morning_excludes_booked(tools):
    result = tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03", "window": "morning"})
    assert result["ok"] and "09:15" not in result["slots"] and "09:45" not in result["slots"]
    assert result["slots"][:3] == ["09:00", "09:30", "10:00"]


@pytest.mark.parametrize(
    "date,doctor,reason",
    [("2026-10-04", "dr_rao", "no_clinic_hours"), ("2026-10-02", "dr_rao", "clinic_holiday"),
     ("2026-10-06", "dr_sethi", "doctor_on_leave"), ("2026-10-09", "dr_rao", "doctor_on_leave")],
)
def test_closed_days_return_no_slots_and_say_why(tools, date, doctor, reason):
    result = tools.call("search_slots", {"doctor_id": doctor, "date": date})
    assert result["ok"] and result["slots"] == [] and result["closed_reason"] == reason


def test_overlapping_windows_do_not_duplicate_slots(tools):
    # Dr. Rao's Monday windows overlap (09:00-12:00 and 11:45-15:00) in clinic.json.
    slots = tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-12"})["slots"]
    assert len(slots) == len(set(slots)) and slots == sorted(slots)
    assert "11:45" in slots and "14:45" in slots and "15:00" not in slots


# ------------------------------------------------------------ malformed input
@pytest.mark.parametrize(
    "name,args,code",
    [
        ("search_slots", {"doctor_id": "dr_rao"}, "MISSING_ARGUMENT"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "3rd October"}, "INVALID_DATE"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "2026-02-30"}, "INVALID_DATE"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "2026-09-30"}, "DATE_IN_PAST"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "2031-10-03"}, "DATE_TOO_FAR"),
        ("search_slots", {"doctor_id": "dr_nobody", "date": "2026-10-03"}, "UNKNOWN_DOCTOR"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03", "window": "midnight"}, "INVALID_WINDOW"),
        ("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03", "bogus": 1}, "UNKNOWN_ARGUMENT"),
        ("search_slots", {"doctor_id": 7, "date": "2026-10-03"}, "INVALID_TYPE"),
        ("book_appointment", {"patient_id": "pt_0013", "doctor_id": "dr_rao", "date": "2026-10-03", "start": "9am"}, "INVALID_TIME"),
        ("book_appointment", {"patient_id": "pt_0013", "doctor_id": "dr_rao", "date": "2026-10-03", "start": "09:10"}, "INVALID_TIME"),
        ("book_appointment", {"patient_id": "pt_9999", "doctor_id": "dr_rao", "date": "2026-10-03", "start": "09:00"}, "UNKNOWN_PATIENT"),
        ("cancel_appointment", {"appointment_id": "ap_9999", "actor_patient_id": "pt_0004"}, "UNKNOWN_APPOINTMENT"),
        ("lookup_patient", {}, "MISSING_ARGUMENT"),
        ("lookup_patient", {"phone": "12345"}, "INVALID_PHONE"),
        ("escalate_to_human", {"reason": "because"}, "INVALID_REASON"),
        ("delete_everything", {}, "UNKNOWN_TOOL"),
    ],
)
def test_malformed_arguments_give_specific_errors(tools, name, args, code):
    result = tools.call(name, args)
    assert error_code(result) == code
    assert result["error"]["message"]  # always actionable, never a bare 500


def test_non_dict_arguments_are_rejected_not_crashed(tools):
    assert error_code(tools.call("search_slots", ["dr_rao"])) == "INVALID_ARGUMENTS"
    assert error_code(tools.call(None, {})) == "UNKNOWN_TOOL"


# --------------------------------------------------------------------- booking
def book(tools, patient="pt_0013", doctor="dr_rao", date="2026-10-03", start="09:00", **extra):
    return tools.call("book_appointment", {"patient_id": patient, "doctor_id": doctor, "date": date, "start": start, **extra})


def test_book_then_slot_is_gone(tools):
    result = book(tools)
    assert result["ok"] and result["appointment"]["appointment_id"] == "ap_0026"
    assert "09:00" not in tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-03"})["slots"]


def test_cannot_book_an_existing_booking(tools):
    result = book(tools, date="2026-10-08", start="09:00")  # ap_0015
    assert error_code(result) == "SLOT_TAKEN" and result["error"]["alternatives"]


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"date": "2026-10-04"}, "NO_CLINIC_HOURS"),
        ({"date": "2026-10-02"}, "CLINIC_CLOSED"),
        ({"date": "2026-10-09"}, "DOCTOR_ON_LEAVE"),
        ({"start": "13:30"}, "NOT_A_SLOT"),  # Saturday window ends 13:00
        ({"start": "12:45"}, None),          # last slot that fits before 13:00
        ({"start": "13:00"}, "NOT_A_SLOT"),
    ],
)
def test_booking_outside_hours_is_refused_by_the_tool_layer(tools, kwargs, code):
    result = book(tools, **kwargs)
    assert (result["ok"] is True) if code is None else (error_code(result) == code)


def test_two_conversations_racing_for_one_slot_only_one_wins():
    clinic = Clinic(today="2026-10-01")
    layer = ToolLayer(clinic)
    patients = [f"pt_{n:04d}" for n in range(10, 40) if n not in (31,)]
    outcomes, barrier = [], threading.Barrier(len(patients))

    def worker(patient_id):
        barrier.wait()
        outcomes.append(layer.call("book_appointment", {
            "patient_id": patient_id, "doctor_id": "dr_rao", "date": "2026-10-03", "start": "11:00"}))

    threads = [threading.Thread(target=worker, args=(p,)) for p in patients]
    [t.start() for t in threads]
    [t.join() for t in threads]
    wins = [o for o in outcomes if o["ok"]]
    assert len(wins) == 1
    assert all(error_code(o) == "SLOT_TAKEN" for o in outcomes if not o["ok"])
    live = clinic._conn.execute(
        "SELECT COUNT(*) FROM appointments WHERE doctor_id='dr_rao' AND date='2026-10-03' AND start='11:00' AND status='booked'"
    ).fetchone()[0]
    assert live == 1


def test_storage_layer_rejects_a_double_booking_even_if_the_app_check_is_bypassed():
    import sqlite3
    clinic = Clinic(today="2026-10-01")
    with pytest.raises(sqlite3.IntegrityError):
        clinic._conn.execute(
            "INSERT INTO appointments VALUES ('ap_9001','pt_0013','dr_rao','2026-10-08','09:00','09:15','booked',NULL)"
        )


def test_state_does_not_leak_between_clinic_instances():
    first = ToolLayer(Clinic(today="2026-10-01"))
    assert book(first)["ok"]
    assert book(ToolLayer(Clinic(today="2026-10-01")))["ok"]  # fresh clinic: same slot is free again


# ---------------------------------------------------------------- authorisation
def test_guardian_can_book_for_ward_but_neighbour_cannot(tools):
    assert book(tools, patient="pt_0006", doctor="dr_sethi", date="2026-10-08", start="17:00", booked_by="pt_0008")["ok"]
    result = book(tools, patient="pt_0012", date="2026-10-03", start="09:00", booked_by="pt_0020")
    assert error_code(result) == "NOT_AUTHORISED"


def test_cannot_cancel_someone_elses_appointment(tools):
    result = tools.call("cancel_appointment", {"appointment_id": "ap_0003", "actor_patient_id": "pt_0020"})
    assert error_code(result) == "NOT_AUTHORISED"
    assert tools.clinic.appointment("ap_0003")["status"] == "booked"


def test_cancel_own_then_cancel_again(tools):
    assert tools.call("cancel_appointment", {"appointment_id": "ap_0002", "actor_patient_id": "pt_0004"})["ok"]
    assert error_code(tools.call("cancel_appointment", {"appointment_id": "ap_0002", "actor_patient_id": "pt_0004"})) == "ALREADY_CANCELLED"


# ------------------------------------------------------------------ reschedule
def test_reschedule_moves_in_place_and_frees_the_old_slot(tools):
    result = tools.call("reschedule_appointment", {"appointment_id": "ap_0001", "new_date": "2026-10-03", "new_start": "10:00", "actor_patient_id": "pt_0001"})
    assert result["ok"] and result["appointment"]["appointment_id"] == "ap_0001" and result["previous"]["start"] == "09:30"
    assert "09:30" in tools.call("search_slots", {"doctor_id": "dr_rao", "date": "2026-10-01"})["slots"]


def test_reschedule_into_taken_slot_changes_nothing(tools):
    result = tools.call("reschedule_appointment", {"appointment_id": "ap_0001", "new_date": "2026-10-03", "new_start": "09:15", "actor_patient_id": "pt_0001"})
    assert error_code(result) == "SLOT_TAKEN"
    assert tools.clinic.appointment("ap_0001")["start"] == "09:30"


def test_reschedule_to_same_slot_is_rejected(tools):
    result = tools.call("reschedule_appointment", {"appointment_id": "ap_0001", "new_date": "2026-10-01", "new_start": "09:30", "actor_patient_id": "pt_0001"})
    assert error_code(result) == "SAME_SLOT"


# ---------------------------------------------------------------- lookup_patient
def test_ambiguous_surname_returns_all_candidates_never_one(tools):
    result = tools.call("lookup_patient", {"name": "Sharma"})
    assert result["match"] == "ambiguous"
    assert {c["patient_id"] for c in result["candidates"]} == {"pt_0001", "pt_0002", "pt_0003"}
    assert "upcoming_appointments" not in result  # nothing is revealed until identity is unique


def test_phone_resolves_the_sharma_ambiguity(tools):
    result = tools.call("lookup_patient", {"name": "Rajesh Kumar Sharma", "phone": "98122 00011"})
    assert result["match"] == "unique" and result["candidates"][0]["patient_id"] == "pt_0001"
    assert result["upcoming_appointments"][0]["appointment_id"] == "ap_0001"


def test_shared_phone_is_not_an_identity(tools):
    assert tools.call("lookup_patient", {"phone": "9812200166"})["match"] == "ambiguous"  # Gupta family
    assert tools.call("lookup_patient", {"phone": "9812200466"})["match"] == "ambiguous"  # Rawats


def test_name_with_wrong_phone_matches_nobody(tools):
    assert tools.call("lookup_patient", {"name": "Priya Nair", "phone": "9812200135"})["match"] == "none"


def test_similar_spellings_stay_ambiguous_without_a_phone(tools):
    result = tools.call("lookup_patient", {"name": "Imran Qureshi"})
    assert result["match"] == "ambiguous"
    assert tools.call("lookup_patient", {"name": "Imran Qureshi", "phone": "9812200228"})["candidates"][0]["patient_id"] == "pt_0010"


def test_first_name_alone_is_not_enough(tools):
    assert tools.call("lookup_patient", {"name": "Priya"})["match"] == "ambiguous"
    assert tools.call("lookup_patient", {"name": "Priya Nair"})["match"] == "unique"


def test_ward_lookup_picks_the_right_child_of_two_lookalikes(tools):
    result = tools.call("lookup_patient", {"name": "Aarav", "ward_of": "pt_0008"})
    assert result["match"] == "unique" and result["candidates"][0]["patient_id"] == "pt_0006"
    assert tools.call("lookup_patient", {"name": "Aarav", "ward_of": "pt_0020"})["match"] == "none"


# -------------------------------------------------------------------- escalate
def test_escalate_records_a_handoff(tools):
    result = tools.call("escalate_to_human", {"reason": "clinical_urgent", "detail": "chest pain", "caller_said": "seene mein dard"})
    assert result["ok"] and result["handoff_id"] == "ho_0001"
    assert tools.clinic.escalations[0]["reason"] == "clinical_urgent"
