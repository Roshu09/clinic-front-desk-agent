"""Deterministic safety detectors. These always run, whatever the LLM says.

The LLM may *add* an escalation (it understands phrasing a regex never will) but it can
never remove one these rules raise. Recall is deliberately favoured over precision for
clinical urgency: a false escalation costs a human a minute; a missed chest-pain call
rejects the whole submission.

Patterns cover English, romanised Hindi (several spellings) and Devanagari.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .dates import normalize

# ---- clinical urgency ---------------------------------------------------------------
# (label, regex, negatable). A negatable pattern is ignored when the caller immediately
# denies it ("seene mein dard nahi hai", "no chest pain"). Inherently negative phrases
# ("saans nahi aa rahi") are not negatable.
URGENT_PATTERNS: list[tuple[str, str, bool]] = [
    ("chest pain", r"(seene|sine|seena|chhati|chaati|chati|chhaati)\s*(mein|me|main|mai|ke|ki)?\s*(\w+\s+){0,3}?(dard|pain|jalan|bhari|bhaari|dabav|jakdan|bhaaripan)", True),
    ("chest pain", r"chest\s*(\w+\s+){0,2}?(pain|tightness|pressure|discomfort|heaviness|hurts?)", True),
    ("chest pain", r"सीने\s*(में|मे)?\s*(\S+\s+){0,3}?(दर्द|जकड़न|भारीपन|जलन)", True),
    ("heart attack", r"heart\s*attack|dil\s*ka\s*daura|हार्ट\s*अटैक|दिल\s*का\s*दौरा|dil\s*(mein|me)\s*dard|दिल\s*में\s*दर्द", True),
    ("breathing difficulty", r"saans?\s*(\w+\s+){0,3}?(phool|phul|ruk|band|atak|ghut)", False),
    ("breathing difficulty", r"saans?\s*(\w+\s+){0,3}?(nahi|nahin|nhi)\s*(aa|a\b|le|ho)", False),
    ("breathing difficulty", r"saans?\s*(lene|lene)\s*(mein|me)\s*(\w+\s+){0,2}?(takleef|dikkat|problem|mushkil|taklif)", False),
    ("breathing difficulty", r"sans\s*(phool|nahi|ruk)|dam\s*(ghut|phool)", False),
    ("breathing difficulty", r"breath(ing|less|lessness)|short(ness)?\s*of\s*breath|(can'?t|cannot|unable\s*to|difficulty|trouble|struggling\s*to)\s*(\w+\s+)?breath", False),
    ("breathing difficulty", r"सांस\s*(\S+\s+){0,3}?(फूल|नहीं|रुक|लेने)|साँस\s*(\S+\s+){0,3}?(फूल|नहीं|रुक|लेने)", False),
    ("unconscious", r"behosh|bhosh|बेहोश|unconscious|passed\s*out|fainted|collaps(ed|e)|hosh\s*(\w+\s+)?(nahi|nahin|kho)|unresponsive|not\s*responding|response\s*nahi|aankh\s*nahi\s*khol", False),
    ("seizure", r"\bdaura\b|\bfits?\b|seizure|convuls|mirgi|दौरा|मिर्गी|akad(an)?\s*(\w+\s+)?(raha|rahi)", False),
    ("stroke symptoms", r"lakwa|लकवा|paralys|chehra\s*(\w+\s+)?tedha|face\s*(is\s*)?droop|slurred|zubaan\s*(\w+\s+)?(ladkhad|atak)|bol\s*nahi\s*pa|ek\s*taraf\s*(\w+\s+){0,3}?(kamzor|sunn|numb|kaam\s*nahi)|stroke|sudden(ly)?\s*(\w+\s+){0,2}?(weakness|numbness|vision\s*loss|blind)", False),
    ("severe bleeding", r"(bahut|bohot|bahot|zyada|jyada|heavy|severe|nonstop|non-stop)\s*(\w+\s+){0,2}?(khoon|blood|bleeding)|khoon\s*(\w+\s+){0,3}?(nahi\s*ruk|ruk\s*nahi|beh\s*raha|bah\s*raha|behne)|bleeding\s*(won'?t|will\s*not|not|does\s*not|doesn'?t)\s*stop|(vomit|vomiting|cough|coughing|throwing\s*up)\s*(up\s*)?blood|khoon\s*(ki|ka)\s*(ulti|khansi|ulti)", False),
    ("poisoning or overdose", r"zeher|zehar|ज़हर|जहर|poison|overdose|(bahut|zyada|jyada)\s*(\w+\s+){0,2}?(goli|goliyan|tablets?|dawai)\s*(\w+\s+){0,2}?(kha|le)\s*(li|liya|lee)|swallowed\s*(\w+\s+){0,2}?(pills|tablets|bleach|acid)", False),
    ("suicidal thoughts or self-harm", r"suicid|khudkushi|khud\s*kushi|aatmahatya|आत्महत्या|खुदकुशी|jaan\s*(de|dena|dene)|जान\s*(दे|देना)|marna\s*chah|mar\s*jana\s*chah|mar\s*jaana\s*chah|jeena\s*nahi\s*chah|khud\s*ko\s*(khatam|hurt|nuksan|maar)|end\s*(my|his|her)\s*life|kill\s*(myself|himself|herself)|want\s*to\s*die|self[-\s]*harm|cut\s*(myself|my\s*wrist)", False),
    ("severe allergic reaction", r"anaphyla|(throat|gala|gale)\s*(\w+\s+){0,3}?(swell|sooj|suj|band|tight)|(face|chehra|hont|hothon|jeebh|tongue|lips?)\s*(\w+\s+){0,3}?(swell|sooj|suj)", False),
    ("snake or scorpion bite", r"saanp\s*(ne|ke)?\s*(\w+\s+)?(kaat|daans|dasa)|snake\s*bite|bichhu\s*(ne)?\s*(\w+\s+)?(kaat|daans)|scorpion\s*sting", False),
    ("infant in distress", r"(baby|bachcha|bachche|bachchi|shishu|newborn|infant)\s*(\w+\s+){0,5}?(saans|breath|neela|neeli|blue|behosh|hosh|respond|unresponsive|nahi\s*uth|dudh\s*nahi|not\s*feeding)", False),
    ("serious injury", r"road\s*accident|accident\s*(ho\s*gaya|hua|mein)|serious(ly)?\s*(injur|hurt)|head\s*injury|sar\s*(mein|me)\s*chot|sir\s*(mein|me)\s*chot|haddi\s*(toot|tut)|bone\s*(is\s*)?broken|fracture|gir\s*(gaya|gayi|gaye)\s*(\w+\s+){0,3}?(chot|khoon|behosh)", False),
    ("labour or pregnancy emergency", r"labou?r\s*pain|delivery\s*(pain|ka\s*dard)|pani\s*(toot|tut)\s*gaya|water\s*broke|garbh\w*\s*(\w+\s+){0,4}?(khoon|bleeding|dard)|pregnan\w*\s*(\w+\s+){0,4}?(bleeding|khoon)", False),
    ("emergency", r"\bemergency\b|एमरजेंसी|इमरजेंसी|\bambulance\b|एम्बुलेंस|turant\s*(doctor|ilaaj|help)|jaan\s*ka\s*khatra|life[-\s]*threatening|dying", False),
    ("severe pain", r"(bahut|bohot|bahot|behad|asahniya|asahaniya|unbearable|severe|extreme|excruciating|sharp|sudden)\s*(\w+\s+){0,2}?(tez\s*)?(dard|pain)|dard\s*(\w+\s+){0,2}?(bardasht|sehen)\s*(\w+\s+)?nahi", True),
    ("cardiac symptoms", r"(pasina|paseena|sweating)\s*(\w+\s+){0,5}?(ghabrahat|ghabrahat|chakkar|nausea|ulti)|(ghabrahat|chakkar)\s*(\w+\s+){0,5}?(pasina|paseena|sweating)", False),
]

NEGATION_AFTER = re.compile(r"^\s*(?:[\w']+\s+){0,2}?(nahi|nahin|nhi|nahee|not|never|nope)\b")
NEGATION_BEFORE = re.compile(r"\b(no|not|without|nahi|nahin|koi\s+nahi|never)\s+(?:\w+\s+){0,2}$")
COMPILED_URGENT = [(label, re.compile(pattern), negatable) for label, pattern, negatable in URGENT_PATTERNS]


def clinical_urgency(text: str) -> Optional[tuple[str, str]]:
    """Return (label, matched text) if the utterance describes something needing a clinician now."""
    t = normalize(text)
    for label, pattern, negatable in COMPILED_URGENT:
        for match in pattern.finditer(t):
            if negatable and (NEGATION_AFTER.match(t[match.end():]) or NEGATION_BEFORE.search(t[:match.start()])):
                continue
            return label, match.group(0)
    return None


# ---- medical advice (a clinical judgement the front desk cannot give) ----------------
MED_TERM = re.compile(
    r"crocin|paracetamol|dolo|ibuprofen|brufen|combiflam|aspirin|disprin|antibiotic|azithro\w*|amoxi\w*|cetirizine|"
    r"medicines?|medication|dawai|dawa\b|dava\b|goli|tablet|capsule|syrup|injection|\bdose\b|dosage|\bmg\b|\bml\b|"
    r"दवा|दवाई|गोली|खुराक|insulin|steroid|painkiller"
)
QUESTION_CUE = re.compile(
    r"\?|\bkya\b|kitni|kitna|\bkab\b|kaise|kaun\s*si|konsi|kaunsi|should\s*i|can\s*i|may\s*i|is\s*it\s*(safe|ok|fine)|safe\s*hai|"
    r"le\s*(lun|loon|sakta|sakti|lu\b)|lena\s*chahiye|kha\s*(sakta|sakti|loon|lun|lu\b)|de\s*(sakta|sakti|du\b|doon)|"
    r"how\s*(much|many|long|often)|kitni\s*der|ya\s*nahi|क्या|कितनी|कितना"
)
ADVICE_PHRASE = re.compile(
    r"kya\s*(karun|karoon|karna\s*chahiye|karein|kare)\b|what\s*should\s*i\s*do|(yeh|ye|is)\s*(\w+\s+){0,2}?(serious|gambhir|khatarnak|dangerous)|"
    r"serious\s*(hai|to\s*nahi|toh\s*nahi)|(kya|is\s*it)\s*(\w+\s+){0,3}?(cancer|tb\b|diabetes|infection|dengue|malaria|typhoid)|"
    r"report\s*(\w+\s+){0,2}?(normal|theek|sahi|dekh)|side\s*effects?|(dawai|medicine)\s*(\w+\s+){0,2}?(badal|band|kab\s*tak)|"
    r"diagnos|kya\s*(bimari|beemari|problem)\s*hai|konsi\s*bimari|kaunsi\s*bimari|home\s*remed(y|ies)|gharelu\s*(nuskha|ilaaj)|"
    r"kitni\s*der\s*(mein|me)\s*(utar|theek|aaram)"
)


def seeks_medical_advice(text: str) -> bool:
    t = normalize(text)
    return bool(ADVICE_PHRASE.search(t)) or bool(MED_TERM.search(t) and QUESTION_CUE.search(t))


# ---- legitimate but outside the front desk's remit -------------------------------------
OUT_OF_SCOPE = re.compile(
    r"\bbill(ing|s)?\b|invoice|payment|refund|insurance|mediclaim|cashless|\bclaim\b|discount|fees?\s*(kitni|kitna|kya|how)|"
    r"\bcharges?\b|consultation\s*fee|report\s*(\w+\s+){0,2}?(kab|mil|ready|aayi|aai|collect)|lab\s*report|test\s*result|"
    r"\bx-?ray\b|\bmri\b|\bscan\b|blood\s*test|home\s*visit|ghar\s*(par|pe)\s*(aa|bula|visit)|prescription|refill|"
    r"medical\s*certificate|fitness\s*certificate|leave\s*letter|doctor\s*(ka|ke)\s*(number|phone|mobile)|"
    r"video\s*consult|online\s*consult|telemedicine|new\s*patient|register\s*(me|mujhe|karna|karwana)|registration|"
    r"naya\s*patient|pharmacy|medicine\s*delivery|complaint|shikayat|job|vacancy|salary"
)


def out_of_scope_topic(text: str) -> Optional[str]:
    match = OUT_OF_SCOPE.search(normalize(text))
    return match.group(0) if match else None


# ---- prompt injection, authority claims and bulk actions --------------------------------
INJECTION = re.compile(
    r"ignore\s*(all\s*|any\s*)?(your\s*|the\s*|my\s*)?(previous|prior|above|earlier|all)?\s*(instructions?|rules?|prompts?|guidelines)|"
    r"disregard\s*(\w+\s+){0,3}?(instructions?|rules?)|forget\s*(\w+\s+){0,3}?(instructions?|rules?)|"
    r"(admin|administrator|developer|debug|god|root|sudo|dan)\s*mode|you\s*are\s*now|from\s*now\s*on\s*you|pretend\s*(to\s*be|you)|"
    r"act\s*as\s*(an?\s*)?(admin|administrator|system|developer)|system\s*prompt|reveal\s*(your|the)\s*(instructions?|prompt)|"
    r"(print|show|repeat)\s*(your|the)\s*(instructions?|prompt|rules)|new\s*instructions?\s*:|\[\s*system\s*\]|<\s*system\s*>|"
    r"authori[sz]ed\s*(internal\s*)?(test|override|request)|this\s*is\s*(a\s*)?(test|drill)\b|override\s*(all\s*)?(safety|rules|checks)|"
    r"i\s*am\s*(the\s*|an?\s*)?(doctor|admin|administrator|owner|manager|developer|engineer|staff|clinic)|"
    r"main\s*(doctor|admin|manager|owner|developer)\s*hoon|pichhle\s*(instructions?|nirdesh)\s*(bhool|ignore)|"
    r"instructions?\s*(ignore|bhool)|\b(ap|pt|ho)_\d{2,}\b|^\s*system\s*[:>-]|\bsystem\s*(override|message|instruction|command|task|notice)|maintenance\s*task|bypass\s*(\w+\s+){0,2}?(check|verification|authori[sz]ation)|skip\s*(\w+\s+){0,2}?(verification|checks?)"
)
BULK = re.compile(
    r"(every|all|saare|sare|sabhi|sab|poore|puri|entire|each)\s*(\w+\s+){0,4}?(appointments?|bookings?|patients?)|"
    r"(appointments?|bookings?)\s*(\w+\s+){0,3}?(sab|sabhi|saare|sare|all|everything)\s*(\w+\s+){0,2}?(cancel|delete|hata|remove)|"
    r"cancel\s*(everything|all)|delete\s*(everything|all|the\s*database)|sab\s*kuch\s*(cancel|delete|hata)|wipe|drop\s*table"
)


def injection_attempt(text: str) -> Optional[str]:
    match = INJECTION.search(normalize(text))
    return match.group(0) if match else None


def bulk_request(text: str) -> Optional[str]:
    match = BULK.search(normalize(text))
    return match.group(0) if match else None


@dataclass
class SafetyReading:
    urgent: Optional[tuple[str, str]]
    advice: bool
    out_of_scope: Optional[str]
    injection: Optional[str]
    bulk: Optional[str]


def read_safety(text: str) -> SafetyReading:
    return SafetyReading(
        urgent=clinical_urgency(text),
        advice=seeks_medical_advice(text),
        out_of_scope=out_of_scope_topic(text),
        injection=injection_attempt(text),
        bulk=bulk_request(text),
    )
