"""Rule-based understanding of one caller turn -> TurnFacts.

This is the deterministic baseline. It runs offline, costs nothing and gives identical
output every time. The optional LLM extractor (nlu_llm.py) is layered on top of it and is
only allowed to fill gaps or add safety flags, never to override a value computed here.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Optional

from .dates import (DAYPART_LOOKUP, MONTHS, WEEKDAY_LOOKUP, RELATIVE, DateMention, find_date_mentions, normalize,
                    read_dates, read_time)
from .matching import name_tokens, normalise_phone
from .safety import read_safety

INTENTS = ("book", "reschedule", "cancel")


@dataclass
class TurnFacts:
    text: str
    # safety
    urgent: Optional[str] = None            # label of the clinical emergency, if any
    advice: bool = False                    # asked for a clinical judgement
    out_of_scope: Optional[str] = None      # legitimate request outside the front desk's remit
    injection: Optional[str] = None
    bulk: Optional[str] = None
    # task
    intent: Optional[str] = None
    doctor_id: Optional[str] = None
    any_doctor: bool = False
    dates: list[str] = field(default_factory=list)          # ISO dates this turn asks for, earliest first
    date_role: Optional[str] = None                          # "existing" | "target" | None (decided by cues)
    existing_dates: list[str] = field(default_factory=list)  # explicit "my appointment on X"
    date_conflict: bool = False
    time: Optional[str] = None                               # exact HH:MM
    window: Optional[str] = None                             # morning / afternoon / evening
    any_time: bool = False
    # identity
    caller_name: Optional[str] = None
    subject_name: Optional[str] = None                       # who the appointment is for, if not the caller
    relation: Optional[str] = None
    phone: Optional[str] = None
    declined: bool = False                                   # "I'll call later", "never mind"
    source: str = "rules"


# ---------------------------------------------------------------- doctors
SPECIALITY_WORDS = {
    "general physician": ["general physician", "physician", "general doctor", "family doctor", "gp"],
    "paediatrics": ["paediatric", "pediatric", "paediatrician", "pediatrician", "child specialist", "children's doctor",
                    "bachon ke doctor", "bachchon ke doctor", "baccho ke doctor", "bachcho ke doctor"],
}
ANY_DOCTOR = re.compile(r"koi\s*bhi\s*doctor|any\s*doctor|jo\s*bhi\s*doctor|kisi\s*bhi\s*doctor|doctor\s*koi\s*bhi|jo\s*bhi\s*available")
ANY_TIME = re.compile(r"koi\s*bhi\s*(time|samay|waqt|slot)|any\s*time|kisi\s*bhi\s*(time|samay)|jab\s*bhi|jo\s*bhi\s*(time|slot)|time\s*koi\s*bhi|anytime|flexible")
DECLINED = re.compile(r"baad\s*(mein|me)\s*call|call\s*(you\s*)?later|rehne\s*do|rahne\s*do|chhod\s*do|chod\s*do|never\s*mind|nevermind|forget\s*it|koi\s*baat\s*nahi|nahi\s*chahiye|not\s*now|abhi\s*nahi")

CANCEL_VERB = re.compile(r"cancel|\bradd\b|raddh|hata\s*(do|dijiye|dena|de)\b|रद्द|कैंसिल|nahi\s*aa\s*(sakta|sakti|paunga|paungi)|appointment\s*(mat|nahi)\s*chahiye")
RESCHEDULE_VERB = re.compile(r"re-?schedule|\bshift\b|postpone|prepone|badal|\bchange\b|aage\s*kar|pichhe\s*kar|dusre\s*din|\bmove\b|re-?book|बदल|दूसरे\s*दिन")
EXISTING_CUE = re.compile(r"(mera|meri|mere|my)\s*(\w+\s+){0,3}?appointment\s*(\w+\s+){0,3}?(hai|tha|booked|fixed)|already\s*(have|booked)|appointment\s*(hai|booked|fixed)\b")
TARGET_CUE = re.compile(r"\b(use|isko|ise|usko|isse|usse|isey)\b|karwana\s*hai|kar\s*do\b|kar\s*dijiye|\bshift\b")
BOOK_CUE = re.compile(
    r"appointment|apointment|appoinment|book\b|booking|milna|mil\s*sakta|mil\s*sakti|dikhana|dikhwana|dikhani|dikha\b|consult|"
    r"\bslot\b|time\s*mil|check\s*up|checkup|aa\s*sakta|aa\s*sakti|aana\s*hai|visit|मिलना|दिखाना|अपॉइंटमेंट|बुक|"
    r"ke\s*(saath|sath|paas)\s*(\w+\s+){0,6}?(chahiye|chahie|karwana|karna|lena|hai)"
)

RELATIONS = {
    "bete": "son", "beta": "son", "son": "son", "beti": "daughter", "daughter": "daughter", "bachche": "child",
    "bachcha": "child", "bachchi": "child", "child": "child", "kid": "child", "baby": "child",
    "bhai": "brother", "brother": "brother", "behen": "sister", "bahan": "sister", "sister": "sister",
    "maa": "mother", "mummy": "mother", "mother": "mother", "papa": "father", "father": "father",
    "wife": "spouse", "husband": "spouse", "patni": "spouse", "pati": "spouse", "padosi": "neighbour",
    "neighbour": "neighbour", "neighbor": "neighbour", "dost": "friend", "friend": "friend",
    "boss": "employer", "employee": "employee", "colleague": "colleague", "grandfather": "grandparent",
    "grandmother": "grandparent", "dada": "grandparent", "dadi": "grandparent", "nana": "grandparent", "nani": "grandparent",
}
RELATION_RE = "|".join(sorted(RELATIONS, key=len, reverse=True))

NAME_STOPWORDS = {
    "main", "mai", "mera", "mere", "meri", "mujhe", "hum", "hamara", "ji", "haan", "han", "nahi", "nahin", "hello", "hi",
    "hey", "namaste", "namaskar", "dr", "doctor", "accha", "acha", "theek", "thik", "bas", "kal", "aaj", "parso", "subah",
    "shaam", "dopahar", "raat", "ignore", "cancel", "number", "waise", "koi", "arre", "are", "ek", "please", "sir",
    "madam", "appointment", "tareekh", "ok", "okay", "yes", "no", "sorry", "thanks", "thank", "yeh", "ye", "woh", "wo",
    "aur", "ya", "toh", "to", "phir", "fir", "abhi", "bhi", "unka", "unki", "unke", "iska", "iski", "uska", "uski",
    "for", "the", "this", "that", "can", "could", "would", "i", "my", "we", "our", "is", "am", "are", "was", "dear",
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "kya", "kyun", "kaise", "kab", "kitna",
    "bol", "bolo", "boliye", "namastey", "pranam", "good", "morning", "evening", "afternoon", "night", "mrs", "mr", "ms",
    "shri", "smt", "sahab", "bhaiya", "didi", "aunty", "uncle", "rao", "sethi", "anjali", "vikram", "october", "november",
    "december", "clinic", "sunrise", "crocin", "paracetamol", "dolo",
} | set(WEEKDAY_LOOKUP) | set(MONTHS) | set(RELATIONS) | set(RELATIVE) | set(DAYPART_LOOKUP)

CAPITAL_SEQUENCE = re.compile(r"(?:[A-Z][a-z'’]+|[A-Z]\.)(?:\s+(?:[A-Z][a-z'’]+|[A-Z]\.))*")
PHONE_RE = re.compile(r"(?<![\d])(?:\+?\s*91[\s-]?|0)?(?:\d[\s-]?){9}\d(?![\d])")


def _doctor_matchers(doctors: list[dict]) -> list[tuple[str, re.Pattern]]:
    matchers = []
    for doctor in doctors:
        words = {w for w in name_tokens(doctor["name"]) if w != "dr" and len(w) > 2}
        words |= set(SPECIALITY_WORDS.get(doctor["speciality"].casefold(), []))
        pattern = "|".join(rf"(?<![a-z]){re.escape(w)}(?![a-z])" for w in sorted(words, key=len, reverse=True))
        matchers.append((doctor["id"], re.compile(pattern)))
    return matchers


def _find_names(text: str, known_tokens: set[str]) -> list[tuple[int, int, str]]:
    """Name-like spans (start, end, text): capitalised runs plus runs of tokens that exist in the patient list."""
    spans: list[tuple[int, int, str]] = []

    def accept(start: int, end: int, raw: str) -> None:
        words = raw.split()
        kept = [w for w in words if w.rstrip(".").casefold() not in NAME_STOPWORDS]
        if len(kept) != len(words) or not kept:
            # split around stopwords and keep the longest clean run
            runs, run = [], []
            for w in words:
                if w.rstrip(".").casefold() in NAME_STOPWORDS:
                    if run:
                        runs.append(run)
                    run = []
                else:
                    run.append(w)
            if run:
                runs.append(run)
            if not runs:
                return
            best = max(runs, key=len)
            start = text.index(best[0], start)
            raw = " ".join(best)
            end = start + len(raw)
        raw = raw.strip(" ,")
        if len(raw.split()[-1].rstrip(".")) > 1:
            raw = raw.rstrip(".")  # "Sharma." -> "Sharma", but keep the initial in "R. K."
        spans.append((start, start + len(raw), raw))

    for m in CAPITAL_SEQUENCE.finditer(text):
        # "Dr. Rao" / "Doctor Sethi": the doctor is not a person calling
        before = text[max(0, m.start() - 8):m.start()].casefold()
        if re.search(r"(dr\.?|doctor)\s*$", before):
            continue
        words = m.group(0).split()
        sentence_start = not text[:m.start()].strip() or text[:m.start()].rstrip().endswith((".", "!", "?", "…"))
        if len(words) == 1 and sentence_start and words[0].casefold() not in known_tokens and not re.match(
                r"^\W*(ji\b\W*)?(bol\s*(raha|rahi|rha|rhi)|speaking|here)", text[m.end():].casefold()):
            continue  # "Do din se...", "You are now...": a capitalised sentence opener, not a name
        accept(m.start(), m.end(), m.group(0))
    # speech-to-text often loses capitalisation: also accept runs of known name tokens
    if known_tokens:
        for m in re.finditer(r"[^\W\d_]+(?:[\s.]+[^\W\d_]+){0,3}", text, flags=re.UNICODE):
            words = re.findall(r"[^\W\d_]+", m.group(0), flags=re.UNICODE)
            run_start = None
            offset = m.start()
            cursor = offset
            for word in words:
                position = text.index(word, cursor)
                cursor = position + len(word)
                is_known = word.casefold() in known_tokens and word.casefold() not in NAME_STOPWORDS
                if is_known and run_start is None:
                    run_start = position
                if (not is_known) and run_start is not None:
                    accept(run_start, position, text[run_start:position].strip())
                    run_start = None
            if run_start is not None:
                accept(run_start, cursor, text[run_start:cursor].strip())
    # drop spans fully covered by a longer one
    spans = sorted(set(spans), key=lambda s: (s[0], -(s[1] - s[0])))
    result: list[tuple[int, int, str]] = []
    for s in spans:
        if not any(r[0] <= s[0] and s[1] <= r[1] for r in result):
            result.append(s)
    return result


def _assign_name_roles(text: str, spans: list[tuple[int, int, str]], has_phone: bool) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Decide who is calling and who the appointment is for. Returns (caller, subject, relation)."""
    low = text.casefold()
    caller = subject = relation = None
    rel_match = re.search(rf"\b({RELATION_RE})\b", low)
    if rel_match:
        relation = RELATIONS[rel_match.group(1)]
    for start, end, raw in spans:
        before, after = low[:start], low[end:]
        after_head = after[:40]
        if re.match(r"^\W*(ji\b\W*)?(ka|ki|ke)\b", after_head) and re.search(r"appointment|record|booking|slot", after[:60]):
            subject = subject or raw
        elif re.match(r"^\W*(ji\b\W*)?ko\s+(dikha|dikhwa|le\s*jan|lana|check)", after_head):
            subject = subject or raw
        elif re.match(r"^\W*(ji\b\W*)?(ke\s*liye|k\s*liye|ke\s*lie|ki\s*taraf\s*se)\b", after_head):
            subject = subject or raw
        elif re.match(rf"^\W*(ji\b\W*)?(mera|meri|my|hamara)\s*({RELATION_RE})\b", after_head):
            subject = subject or raw
        elif re.search(rf"\b({RELATION_RE})\s*(ka\s*naam\s*)?$", before.rstrip(" ,")):
            subject = subject or raw
        elif re.match(r"^\W*(ji\b\W*)?(bol\s*(raha|rahi)|speaking|here|bol\s*rhi|bol\s*rha)", after_head) or re.search(
                r"(main|mai|mera\s*naam|my\s*name\s*is|i\s*am|i'm|this\s*is|naam)\s*$", before.rstrip(" ,")):
            caller = caller or raw
        elif re.search(r"\b(main|mai|i\s*am|i'm)\b", before) and not re.search(r"(mere|meri)\s*$", before.rstrip(" ,")):
            caller = caller or raw
        elif has_phone or caller is None:
            caller = caller or raw
        else:
            subject = subject or raw
    return caller, subject, relation


def extract(text: str, today: dt.date, doctors: list[dict], known_name_tokens: Optional[set[str]] = None) -> TurnFacts:
    t = normalize(text)
    facts = TurnFacts(text=text)

    safety = read_safety(text)
    facts.urgent = safety.urgent[0] if safety.urgent else None
    facts.advice = safety.advice
    facts.out_of_scope = safety.out_of_scope
    facts.injection = safety.injection
    facts.bulk = safety.bulk
    facts.declined = bool(DECLINED.search(t))

    # intent: cancel beats reschedule beats book
    if CANCEL_VERB.search(t):
        facts.intent = "cancel"
    elif RESCHEDULE_VERB.search(t) or (EXISTING_CUE.search(t) and TARGET_CUE.search(t)):
        facts.intent = "reschedule"
    elif BOOK_CUE.search(t):
        facts.intent = "book"

    # doctor
    found = [doctor_id for doctor_id, pattern in _doctor_matchers(doctors) if pattern.search(t)]
    if len(found) == 1:
        facts.doctor_id = found[0]
    facts.any_doctor = bool(ANY_DOCTOR.search(t))

    # dates and times
    reading = read_dates(text, today)
    facts.dates = [d.isoformat() for d in reading.options]
    facts.date_conflict = reading.conflict
    mentions = find_date_mentions(text, today)
    if mentions and not reading.conflict:
        facts.date_role, facts.existing_dates = _date_roles(t, mentions, facts.intent)
    clock = read_time(text)
    facts.time, facts.window = clock.start, clock.window
    facts.any_time = bool(ANY_TIME.search(t))

    # identity
    phone_match = PHONE_RE.search(text)
    if phone_match:
        facts.phone = normalise_phone(phone_match.group(0))
    scrubbed = text[:phone_match.start()] + " " + text[phone_match.end():] if phone_match else text
    spans = _find_names(scrubbed, known_name_tokens or set())
    caller, subject, relation = _assign_name_roles(scrubbed, spans, has_phone=bool(phone_match))
    if caller is None and subject is None:  # speech-to-text without capitals, name not in the patient list
        cue = re.search(r"(?:^|[.,]\s*)(?:main\s+|mera\s+naam\s+|my\s+name\s+is\s+|this\s+is\s+)?([a-z]+(?:\s+[a-z]+){0,2}?)\s+(?:bol\s*(?:raha|rahi|rha|rhi)|speaking)\b", t)
        if cue and not any(w in NAME_STOPWORDS for w in cue.group(1).split()):
            caller = cue.group(1)
    facts.caller_name, facts.subject_name, facts.relation = caller, subject, relation
    return facts


def _date_roles(t: str, mentions: list[DateMention], intent: Optional[str]) -> tuple[Optional[str], list[str]]:
    """Which dates are 'my existing appointment is on X' versus 'I want it on Y'."""
    existing: list[str] = []
    role: Optional[str] = None
    for index, mention in enumerate(mentions):
        if mention.date is None:
            continue
        after = t[mention.end:mention.end + 35]
        before = t[max(0, mention.start - 25):mention.start]
        is_wish = re.search(r"appointment\W+(\w+\W+){0,2}?(chahiye|chahie|chahta|chahti|lena|leni|book|banwa|karwana|karna|chaahiye)",
                            after) and not re.search(r"appointment\W+(\w+\W+){0,2}?(hai|tha|booked|fixed|cancel|radd)", after[:after.find("chah") if "chah" in after else len(after)])
        if (re.match(r"^\W*(ka|ki|ke|wala|wali)\b\W*(\w+\W+){0,2}appointment", after) and not is_wish) or re.search(
                r"(mera|meri|my)\s*(\w+\s+){0,2}appointment\s*(on|for)?\s*$", before):
            existing.append(mention.date.isoformat())
            if index == len(mentions) - 1:
                role = "existing"
        elif re.search(r"\b(use|isko|ise|usko|to|toh|se\s*badal|shift\s*(it\s*)?to|move\s*(it\s*)?to)\s*$", before) or re.match(
                r"^\W*(ko|par|pe)?\W*(karwana|kar\s*do|kar\s*dijiye|shift|badal)", after):
            if index == len(mentions) - 1:
                role = "target"
    return role, existing
