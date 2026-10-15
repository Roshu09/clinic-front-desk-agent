"""Date and clock-time resolution for Hindi / English / Hinglish utterances.

Pure functions. ``today`` is always passed in: nothing here may read the system clock,
because the evaluation harness sets the date and re-runs on other days.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

WEEKDAYS = {
    0: ["somwar", "somvar", "monday", "सोमवार"],
    1: ["mangalwar", "mangalvar", "mangal", "tuesday", "मंगलवार"],
    2: ["budhwar", "budhvar", "budh", "wednesday", "बुधवार"],
    3: ["guruwar", "guruvar", "veerwar", "virwar", "brihaspatiwar", "thursday", "गुरुवार", "बृहस्पतिवार", "वीरवार"],
    4: ["shukrawar", "shukravar", "shukra", "friday", "शुक्रवार"],
    5: ["shaniwar", "shanivar", "shanivaar", "shani", "saturday", "शनिवार"],
    6: ["raviwar", "ravivar", "ravivaar", "itwar", "itvaar", "sunday", "रविवार"],
}
WEEKDAY_LOOKUP = {word: index for index, words in WEEKDAYS.items() for word in words}

RELATIVE = {
    "aaj": 0, "today": 0, "आज": 0,
    "kal": 1, "tomorrow": 1, "tmrw": 1, "कल": 1,
    "parso": 2, "parson": 2, "parsoon": 2, "परसों": 2, "परसो": 2,
    "narso": 3, "narson": 3, "narsoon": 3, "नरसों": 3,
}
MONTHS = {
    "january": 1, "janwari": 1, "february": 2, "farwari": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "agast": 8, "september": 9, "sitambar": 9, "october": 10, "oct": 10, "aktoobar": 10, "akutubar": 10,
    "november": 11, "navambar": 11, "december": 12, "disambar": 12,
}
NUMBER_WORDS = {
    "ek": 1, "one": 1, "do": 2, "two": 2, "teen": 3, "three": 3, "char": 4, "chaar": 4, "four": 4, "paanch": 5,
    "panch": 5, "five": 5, "chhe": 6, "chheh": 6, "chhah": 6, "che": 6, "six": 6, "saat": 7, "seven": 7, "aath": 8,
    "eight": 8, "nau": 9, "nine": 9, "das": 10, "ten": 10, "gyarah": 11, "gyaarah": 11, "giyarah": 11, "eleven": 11,
    "barah": 12, "baarah": 12, "twelve": 12, "terah": 13, "chaudah": 14, "pandrah": 15, "solah": 16, "satrah": 17,
    "atharah": 18, "unnis": 19, "bees": 20, "ikkis": 21, "baais": 22, "teis": 23, "chaubis": 24, "pachchis": 25,
    "chhabbis": 26, "sattais": 27, "atthais": 28, "untis": 29, "tees": 30, "ikatis": 31,
}
CORRECTION_CUE = re.compile(
    r"nahi\s+nahi|nahin\s+nahin|no\s+no|\bsorry\b|\bactually\b|\bmatlab\b|i\s+mean|\bwait\b|\bruko\b|\bgalat\b|\bbalki\b|"
    r"\binstead\b|\barre\b|नहीं\s+नहीं|\bnahi\s+(?=[a-z0-9]+\s+(?:tareekh|kar|ko\b))"
)


def normalize(text: str) -> str:
    """Casefold, NFKC, map Devanagari digits to ASCII, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = text.translate({0x0966 + i: ord("0") + i for i in range(10)})
    return re.sub(r"\s+", " ", text)


def _word(pattern: str) -> str:
    return rf"(?<![a-z\u0900-\u097f]){pattern}(?![a-z\u0900-\u097f])"


@dataclass
class DateMention:
    start: int
    end: int
    date: Optional[dt.date]
    weekday: Optional[int] = None
    conflict: bool = False


def _day_number_to_date(day: int, today: dt.date, month: Optional[int] = None) -> Optional[dt.date]:
    """Resolve 'the Nth' against ``today``: this month if still ahead, else next month."""
    if month is not None:
        for year in (today.year, today.year + 1):
            try:
                candidate = dt.date(year, month, day)
            except ValueError:
                return None
            if candidate >= today:
                return candidate
        return None
    year, mon = today.year, today.month
    for _ in range(13):
        try:
            candidate = dt.date(year, mon, day)
            if candidate >= today:
                return candidate
        except ValueError:
            pass
        mon += 1
        if mon > 12:
            year, mon = year + 1, 1
    return None


def _next_weekday(weekday: int, today: dt.date) -> dt.date:
    delta = (weekday - today.weekday()) % 7
    return today + dt.timedelta(days=delta or 7)  # "Thursday" said on a Thursday means next week's


def _number_token(raw: str) -> Optional[int]:
    return int(raw) if raw.isdigit() else NUMBER_WORDS.get(raw)


def find_date_mentions(text: str, today: dt.date) -> list[DateMention]:
    t = normalize(text)
    found: list[DateMention] = []
    taken: list[tuple[int, int]] = []

    def add(start: int, end: int, date: Optional[dt.date], weekday: Optional[int] = None) -> None:
        if any(start < e and s < end for s, e in taken):
            return
        taken.append((start, end))
        found.append(DateMention(start, end, date, weekday))

    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", t):
        try:
            add(m.start(), m.end(), dt.date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            add(m.start(), m.end(), None)
    month_names = "|".join(sorted(MONTHS, key=len, reverse=True))
    for m in re.finditer(rf"(?<!\d)(\d{{1,2}})\s*(?:st|nd|rd|th)?\s*(?:of\s+)?({month_names})(?![a-z])", t):
        add(m.start(), m.end(), _day_number_to_date(int(m[1]), today, MONTHS[m[2]]))
    for m in re.finditer(rf"(?<![a-z])({month_names})\s+(\d{{1,2}})(?!\d)(?!\s*(?:baje|:|am|pm))", t):
        add(m.start(), m.end(), _day_number_to_date(int(m[2]), today, MONTHS[m[1]]))
    words = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
    for m in re.finditer(rf"(?<![\d:])(\d{{1,2}}|{words})\s*(?:st|nd|rd|th)?\s*(?:tareekh|tarikh|taareekh|tarik|date|तारीख)", t):
        day = _number_token(m[1])
        add(m.start(), m.end(), _day_number_to_date(day, today) if day and 1 <= day <= 31 else None)
    for m in re.finditer(r"(?<![\d:/.-])(\d{1,2})\s*(?:st|nd|rd|th)(?![a-z])", t):
        add(m.start(), m.end(), _day_number_to_date(int(m[1]), today) if 1 <= int(m[1]) <= 31 else None)
    for m in re.finditer(r"(?<![\d:/.-])(\d{1,2})\s+ko(?![a-z])", t):
        if 1 <= int(m[1]) <= 31:
            add(m.start(), m.end(), _day_number_to_date(int(m[1]), today))
    for m in re.finditer(r"(?<![\d:])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d:])", t):
        try:
            year = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else today.year
            add(m.start(), m.end(), dt.date(year, int(m[2]), int(m[1])))
        except ValueError:
            add(m.start(), m.end(), None)
    for word, offset in RELATIVE.items():
        for m in re.finditer(_word(re.escape(word)), t):
            add(m.start(), m.end(), today + dt.timedelta(days=offset))
    for m in re.finditer(r"day after tomorrow", t):
        add(m.start(), m.end(), today + dt.timedelta(days=2))
    for word, weekday in WEEKDAY_LOOKUP.items():
        for m in re.finditer(_word(re.escape(word)), t):
            add(m.start(), m.end(), _next_weekday(weekday, today), weekday)

    found.sort(key=lambda d: d.start)
    return _merge_weekday_with_number(found, t)


def _merge_weekday_with_number(mentions: list[DateMention], t: str) -> list[DateMention]:
    """'Shanivaar 3 tareekh' is one date, and the two halves must agree."""
    merged: list[DateMention] = []
    skip = False
    for index, current in enumerate(mentions):
        if skip:
            skip = False
            continue
        nxt = mentions[index + 1] if index + 1 < len(mentions) else None
        if nxt and (current.weekday is None) != (nxt.weekday is None) and nxt.start - current.end <= 14:
            between = t[current.end:nxt.start]
            if not CORRECTION_CUE.search(between) and not re.search(r"\b(ya|or)\b", between):
                weekday_part, number_part = (current, nxt) if current.weekday is not None else (nxt, current)
                date = number_part.date
                conflict = date is not None and date.weekday() != weekday_part.weekday
                merged.append(DateMention(min(current.start, nxt.start), max(current.end, nxt.end), date,
                                          weekday_part.weekday, conflict))
                skip = True
                continue
        merged.append(current)
    return merged


@dataclass
class DateReading:
    options: list[dt.date]          # candidate dates, earliest first; >1 means "this or that"
    conflict: bool = False          # the final mention contradicts itself (weekday vs day number)
    correction: bool = False
    all_mentions: int = 0


def read_dates(text: str, today: dt.date) -> DateReading:
    """The date(s) a single utterance asks for. Later mentions beat earlier ones (self-correction)."""
    t = normalize(text)
    mentions = find_date_mentions(text, today)
    if not mentions:
        return DateReading([])
    correction = bool(CORRECTION_CUE.search(t))
    last = mentions[-1]
    if last.conflict or last.date is None:
        return DateReading([], conflict=True, correction=correction, all_mentions=len(mentions))
    options = [last.date]
    if not correction:  # "kal ya parso": alternatives, walk back through ya/or chains
        index = len(mentions) - 1
        while index > 0:
            between = t[mentions[index - 1].end:mentions[index].start]
            if re.fullmatch(r"[\s,]*(?:ya(?: phir| fir)?|or|ya to)[\s,]*", between) and mentions[index - 1].date:
                options.append(mentions[index - 1].date)  # type: ignore[arg-type]
                index -= 1
            else:
                break
    return DateReading(sorted(set(options)), correction=correction, all_mentions=len(mentions))


# ------------------------------------------------------------------------ times
DAYPARTS = {
    "morning": ["subah", "morning", "सुबह", "savere", "subha"],
    "afternoon": ["dopahar", "dopehar", "afternoon", "दोपहर"],
    "evening": ["shaam", "sham", "evening", "शाम"],
    "night": ["raat", "night", "रात"],
}
DAYPART_LOOKUP = {w: part for part, words in DAYPARTS.items() for w in words}


@dataclass
class TimeReading:
    start: Optional[str] = None   # exact HH:MM if the caller named a clock time
    window: Optional[str] = None  # morning / afternoon / evening if they named only a part of the day


def _to_24h(hour: int, minute: int, part: Optional[str], meridiem: Optional[str]) -> Optional[tuple[int, int]]:
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    if meridiem == "am":
        hour = 0 if hour == 12 else hour
    elif meridiem == "pm":
        hour = hour if hour == 12 else hour + 12
    elif hour <= 12 and hour != 0:
        if part == "morning":
            pass
        elif part in ("afternoon", "evening", "night"):
            hour = hour if hour == 12 else hour + 12
        elif hour <= 8:  # no daypart: a clinic never opens at 3am, so "3 baje" means 15:00
            hour += 12
    hour = hour % 24 if hour == 24 else hour
    return (hour, minute) if hour < 24 else None


def read_time(text: str) -> TimeReading:
    t = normalize(text)
    parts = [(m.start(), DAYPART_LOOKUP[m[0]]) for w in DAYPART_LOOKUP for m in re.finditer(_word(re.escape(w)), t)]
    parts.sort()
    words = "|".join(sorted(NUMBER_WORDS, key=len, reverse=True))
    candidates: list[tuple[int, int, int, Optional[str]]] = []  # position, hour, minute, meridiem

    for m in re.finditer(r"(?<![\d:.])(\d{1,2})[:.](\d{2})\s*(am|pm|a\.m\.|p\.m\.)?(?![\d:])", t):
        if m[3] is None and ":" not in m[0] and m[2] not in ("00", "15", "30", "45"):
            continue  # "9.50" is more likely a decimal than 9:50
        candidates.append((m.start(), int(m[1]), int(m[2]), m[3][0] + "m" if m[3] else None))
    for m in re.finditer(r"(?<![\d:.])(\d{1,2})\s*(am|pm)(?![a-z])", t):
        candidates.append((m.start(), int(m[1]), 0, m[2]))
    special_spans: list[tuple[int, int]] = []
    for m in re.finditer(rf"\b(saade|sade|sawa|paune)\s+(\d{{1,2}}|{words})(?:\s*baje)?", t):
        hour = _number_token(m[2])
        if hour:
            special_spans.append((m.start(), m.end()))
            if m[1] in ("saade", "sade"):
                candidates.append((m.start(), hour, 30, None))
            elif m[1] == "sawa":
                candidates.append((m.start(), hour, 15, None))
            else:
                candidates.append((m.start(), hour - 1 if hour > 1 else 12, 45, None))
    for m in re.finditer(r"\b(dedh|der?h)\s*baje", t):
        special_spans.append((m.start(), m.end()))
        candidates.append((m.start(), 1, 30, None))
    for m in re.finditer(r"\bdhai\s*baje", t):
        special_spans.append((m.start(), m.end()))
        candidates.append((m.start(), 2, 30, None))
    for m in re.finditer(rf"(?<![\d:.])(\d{{1,2}}|{words})\s*(?:baje|bje|o'?clock)", t):
        if any(s0 <= m.start() < e0 for s0, e0 in special_spans):
            continue  # "saade teen baje" is one time, not 3:00 plus a stray half
        hour = _number_token(m[1])
        if hour:
            candidates.append((m.start(), hour, 0, None))

    if candidates:
        position, hour, minute, meridiem = max(candidates)  # the last time mentioned wins
        nearest = None
        if parts:
            nearest = min(parts, key=lambda p: abs(p[0] - position))[1]
        resolved = _to_24h(hour, minute, nearest, meridiem)
        if resolved:
            return TimeReading(start=f"{resolved[0]:02d}:{resolved[1]:02d}", window=None)
    if parts:
        part = parts[-1][1]
        return TimeReading(window="evening" if part == "night" else part)
    return TimeReading()
