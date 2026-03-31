from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


FRENCH_MONTHS = {
    "janvier": 1,
    "fevrier": 2,
    "février": 2,
    "mars": 3,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "aout": 8,
    "août": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    "décembre": 12,
}

SECTION_PATTERNS: List[Tuple[str, str]] = [
    (r"offre\s*demande|equilibre", "supply_demand_balance"),
    (r"interconnexion|m[ée]canisme d[' ]ajustement|couplage", "interconnections_market"),
    (r"incident|min|evenement majeur|événement majeur", "major_incidents"),
    (r"telecom|teleconduite|t[ée]l[ée]conduite", "telecom_telecontrol"),
    (r"congestion|tension|transit", "congestion_voltage_transit"),
    (r"s[ée]curit[ée]|sant[ée]|environnement|confidentialit[ée]", "safety_security_environment"),
    (r"contraintes.*jour|contraintes attendues", "constraints_current_day"),
    (r"r[ée]sum[ée]|synth[èe]se", "executive_summary"),
]


def parse_french_datetime(text: str, default_year: Optional[int] = None) -> Optional[str]:
    """Parse French date/time expressions into ISO-8601."""
    if not text:
        return None
    value = text.lower().strip()

    match = re.search(
        r"(\d{1,2})[\/\-\.\s](\d{1,2})[\/\-\.\s](\d{2,4})(?:\D+(\d{1,2})[:h](\d{2}))?",
        value,
    )
    if match:
        day, month, year, hour, minute = match.groups()
        year_int = int(year) + 2000 if len(year) == 2 else int(year)
        dt = datetime(
            year_int,
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
        )
        return dt.isoformat()

    month_name = "|".join(FRENCH_MONTHS.keys())
    match = re.search(
        rf"(\d{{1,2}})\s+({month_name})\s+(\d{{2,4}})(?:\D+(\d{{1,2}})[:h](\d{{2}}))?",
        value,
    )
    if match:
        day, month, year, hour, minute = match.groups()
        year_int = int(year) + 2000 if len(year) == 2 else int(year)
        dt = datetime(
            year_int,
            FRENCH_MONTHS[month],
            int(day),
            int(hour or 0),
            int(minute or 0),
        )
        return dt.isoformat()

    match = re.search(rf"(\d{{1,2}})\s+({month_name})(?:\D+(\d{{1,2}})[:h](\d{{2}}))?", value)
    if match and default_year:
        day, month, hour, minute = match.groups()
        dt = datetime(
            default_year,
            FRENCH_MONTHS[month],
            int(day),
            int(hour or 0),
            int(minute or 0),
        )
        return dt.isoformat()
    return None


def parse_duration_to_minutes(text: str) -> Optional[int]:
    """Convert French duration formats to minutes."""
    if not text:
        return None
    value = text.lower()
    hours = 0
    minutes = 0
    hour_match = re.search(r"(\d+)\s*(h|heure|heures)", value)
    minute_match = re.search(r"(\d+)\s*(min|minute|minutes)", value)
    compact_match = re.search(r"(\d{1,2})[:h](\d{2})", value)
    if compact_match:
        hours = int(compact_match.group(1))
        minutes = int(compact_match.group(2))
    else:
        if hour_match:
            hours = int(hour_match.group(1))
        if minute_match:
            minutes = int(minute_match.group(1))
    if hours == 0 and minutes == 0:
        return None
    return hours * 60 + minutes


def extract_voltage_levels(text: str) -> List[int]:
    matches = re.findall(r"(\d{2,3})\s*k?v", text.lower())
    return [int(m) for m in matches]


def extract_mw_values(text: str) -> List[float]:
    values = re.findall(r"(\d+(?:[.,]\d+)?)\s*mw", text.lower())
    return [float(v.replace(",", ".")) for v in values]


def extract_customer_counts(text: str) -> List[int]:
    values = re.findall(r"(\d[\d\s\.]*)\s*(?:clients?|foyers?)", text.lower())
    cleaned: List[int] = []
    for value in values:
        digits = re.sub(r"[^\d]", "", value)
        if digits:
            cleaned.append(int(digits))
    return cleaned


def detect_section_headers(text: str) -> Optional[str]:
    lower = text.lower()
    for pattern, section_name in SECTION_PATTERNS:
        if re.search(pattern, lower):
            return section_name
    return None


def merge_duplicate_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge duplicate events from summary + detail sections."""
    merged: Dict[str, Dict[str, Any]] = {}
    for event in events:
        key_seed = " ".join(
            [
                str(event.get("title") or ""),
                str(event.get("location", {}).get("substation") or ""),
                str(event.get("start_time") or ""),
                str(event.get("event_type") or ""),
            ]
        ).strip()
        key = re.sub(r"\s+", " ", key_seed.lower())
        if key not in merged:
            merged[key] = event
            continue

        current = merged[key]
        current["page_numbers"] = sorted(
            set((current.get("page_numbers") or []) + (event.get("page_numbers") or []))
        )
        current["actions_taken"] = sorted(
            set((current.get("actions_taken") or []) + (event.get("actions_taken") or []))
        )
        current["raw_evidence"] = (current.get("raw_evidence") or []) + (event.get("raw_evidence") or [])
        current["confidence"] = max(float(current.get("confidence") or 0.0), float(event.get("confidence") or 0.0))

        if not current.get("end_time") and event.get("end_time"):
            current["end_time"] = event["end_time"]
        if current.get("status") in (None, "unknown") and event.get("status"):
            current["status"] = event["status"]
    return list(merged.values())
