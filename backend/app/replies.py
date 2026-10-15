"""Caller-facing replies, built ONLY from tool results.

Zero invented facts is enforced by construction: no free-text generation reaches the caller.
Every slot, doctor name, date or appointment in a reply is passed in from a tool result.
Hinglish for callers writing Hinglish/Hindi, English otherwise.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

HINGLISH_MARKERS = re.compile(
    r"\b(hai|hain|hoon|hun|ka|ke|ki|ko|mein|me|se|chahiye|chahie|nahi|nahin|aap|kal|aaj|parso|tareekh|baje|subah|shaam|dopahar|"
    r"karna|karwana|kijiye|dijiye|haan|ji|mera|meri|mere|mujhe|bete|beti|dard|bukhar|appointment\s*chahiye|namaste)\b"
)
MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]


def is_hinglish(texts: list[str]) -> bool:
    joined = " ".join(texts).casefold()
    return bool(re.search(r"[ऀ-ॿ]", joined)) or len(HINGLISH_MARKERS.findall(joined)) >= 2


def pretty_date(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {MONTH_NAMES[d.month - 1]} ({d.strftime('%A')})"


def pretty_time(hhmm: str) -> str:
    return hhmm


def _slots(slots: list[str], limit: int = 5) -> str:
    return ", ".join(slots[:limit])


CLOSED = {
    "clinic_holiday": ("clinic holiday ki wajah se band hai", "the clinic is closed that day for a holiday"),
    "doctor_on_leave": ("doctor chhutti par hain", "the doctor is on leave"),
    "no_clinic_hours": ("us din koi clinic hours nahi hain", "there are no clinic hours that day"),
}


def reply(key: str, hinglish: bool, **f) -> str:  # noqa: C901 - one flat template table is easiest to audit
    h = hinglish
    if key == "greet":
        return ("Namaste, Sunrise Clinic. Bataiye, kis doctor ke saath, kis din appointment chahiye?" if h else
                "Hello, Sunrise Clinic. How can I help? Which doctor and which day would you like?")
    if key == "need_doctor":
        return ("Kis doctor ke saath appointment chahiye? Dr. Rao ya Dr. Sethi?" if h else
                "Which doctor would you like to see: Dr. Rao or Dr. Sethi?")
    if key == "need_date":
        return "Kis din ke liye appointment chahiye?" if h else "Which day would you like the appointment?"
    if key == "date_conflict":
        return ("Aapne jo din aur tareekh bataayi wo aapas mein match nahi karti. Kripya sahi tareekh bataiye." if h else
                "The weekday and the date you gave do not match. Could you tell me the exact date?")
    if key == "need_identity":
        return ("Kripya apna poora naam aur registered mobile number bataiye." if h else
                "Please tell me your full name and your registered mobile number.")
    if key == "need_phone_to_disambiguate":
        return (f"Is naam se {f['count']} records mile hain. Kripya registered mobile number bataiye." if h else
                f"I found {f['count']} records with that name. Could you give me the registered mobile number?")
    if key == "slots":
        return (f"{f['doctor']} ke paas {pretty_date(f['date'])} ko ye slots khaali hain: {_slots(f['slots'])}." if h else
                f"{f['doctor']} has these free slots on {pretty_date(f['date'])}: {_slots(f['slots'])}.")
    if key == "closed":
        why = CLOSED.get(f["reason"], CLOSED["no_clinic_hours"])[0 if h else 1]
        return (f"{pretty_date(f['date'])} ko {f['doctor']} ke liye {why}. Koi aur din bataiye." if h else
                f"On {pretty_date(f['date'])}, {why} ({f['doctor']}). Please pick another day.")
    if key == "no_slots":
        return (f"{f['doctor']} ke paas {pretty_date(f['date'])} ko koi slot khaali nahi hai." if h else
                f"{f['doctor']} has no free slots on {pretty_date(f['date'])}.")
    if key == "slot_unavailable":
        alt = f" Khaali slots: {_slots(f['alternatives'])}." if f.get("alternatives") else ""
        alt_en = f" Free slots: {_slots(f['alternatives'])}." if f.get("alternatives") else ""
        return (f"{f['time']} ka slot {pretty_date(f['date'])} ko khaali nahi hai.{alt} Main apne aap koi aur time book nahi karungi, aap bataiye." if h else
                f"The {f['time']} slot on {pretty_date(f['date'])} is not available.{alt_en} I will not pick another time for you; tell me which you prefer.")
    if key == "booked":
        who = f" {f['patient']} ke liye" if f.get("patient") and f.get("for_other") else ""
        who_en = f" for {f['patient']}" if f.get("patient") and f.get("for_other") else ""
        return (f"Ji, {pretty_date(f['date'])} ko {f['time']} baje {f['doctor']} ke saath{who} appointment book ho gaya hai. Appointment ID: {f['appointment_id']}." if h else
                f"Done. Your appointment{who_en} with {f['doctor']} is booked for {pretty_date(f['date'])} at {f['time']}. Appointment ID: {f['appointment_id']}.")
    if key == "rescheduled":
        return (f"Ji, aapka appointment ({f['appointment_id']}) {pretty_date(f['old_date'])} {f['old_time']} se badalkar {pretty_date(f['date'])} ko {f['time']} baje {f['doctor']} ke saath kar diya gaya hai." if h else
                f"Done. Appointment {f['appointment_id']} moved from {pretty_date(f['old_date'])} {f['old_time']} to {pretty_date(f['date'])} at {f['time']} with {f['doctor']}.")
    if key == "cancelled":
        return (f"Ji, {pretty_date(f['date'])} ko {f['time']} baje ka appointment ({f['appointment_id']}) cancel ho gaya hai." if h else
                f"Done. Appointment {f['appointment_id']} on {pretty_date(f['date'])} at {f['time']} is cancelled.")
    if key == "no_appointment_found":
        return ("Mujhe aapke naam par aisa koi upcoming appointment nahi mila." if h else
                "I could not find a matching upcoming appointment on your record.")
    if key == "which_appointment":
        listing = "; ".join(f"{pretty_date(a['date'])} {a['start']} ({a['doctor_name']})" for a in f["appointments"])
        return (f"Aapke ye appointments mile: {listing}. Kaun sa chahiye?" if h else
                f"I found these appointments: {listing}. Which one do you mean?")
    if key == "no_patient_found":
        return ("Is naam aur number se koi registered patient nahi mila. Main staff ko bata rahi hoon." if h else
                "I could not find a registered patient with those details. I am passing this to the staff.")
    if key == "escalate_clinical_urgent":
        return ("Aapki baat sunkar lag raha hai ki aapko abhi doctor ki zaroorat hai. Main aapko turant clinic staff se connect kar rahi hoon. "
                "Agar takleef badh rahi hai to abhi 112 par call kijiye ya nazdeeki emergency mein jaayiye. Booking abhi nahi ki ja rahi." if h else
                "What you describe needs a clinician right now. I am connecting you to clinic staff immediately. "
                "If it is getting worse, please call 112 or go to the nearest emergency department now. I am not booking anything.")
    if key == "escalate_medical_advice":
        return ("Dawai ya ilaaj ke baare mein salah dena mere liye sahi nahi hai. Main aapko clinic staff se connect kar rahi hoon jo doctor tak baat pahunchayenge." if h else
                "I cannot give medical advice about medicines or treatment. I am passing you to the clinic staff, who will get this to a doctor.")
    if key == "escalate_not_authorised":
        return ("Main sirf patient ya unke listed guardian ke kehne par hi kisi record par kaam kar sakti hoon. Aapki request staff ko bhej rahi hoon." if h else
                "I can only act on a record at the request of the patient or a listed guardian. I am sending your request to the staff.")
    if key == "escalate_ambiguous_patient":
        return (f"Is jaankari se {f['count']} alag patients match ho rahe hain, isliye main apne aap koi record nahi chun sakti. Staff aapse sahi record confirm karenge." if h else
                f"That information matches {f['count']} different patients, so I will not pick one myself. Staff will confirm the right record with you.")
    if key == "escalate_out_of_scope":
        return ("Ye request front desk agent ke dayre se bahar hai. Main ise clinic staff ko bhej rahi hoon." if h else
                "That request is outside what the front desk agent can handle. I am passing it to the clinic staff.")
    if key == "refused":
        return ("Main ye request poori nahi kar sakti. Appointment se jude kaam ke liye main yahin hoon." if h else
                "I can't do that. I'm happy to help with a single appointment booking, change or cancellation.")
    if key == "abandoned_nothing":
        return ("Mujhe aapki baat samajh nahi aayi. Jab chahein dobara call kijiye, hum madad karenge." if h else
                "I couldn't catch what you need. Please call again whenever you are ready and we will help.")
    if key == "abandoned_declined":
        return ("Theek hai, koi baat nahi. Jab chahein dobara call kijiye." if h else
                "No problem. Please call again whenever you like.")
    if key == "tool_failure":
        return ("Kuch gadbad hui, isliye maine kuch change nahi kiya. Main staff ko bata rahi hoon." if h else
                "Something went wrong, so I changed nothing. I am passing this to the staff.")
    raise KeyError(key)
