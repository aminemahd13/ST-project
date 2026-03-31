from app.utils.pdf_parsing import (
    extract_customer_counts,
    extract_mw_values,
    extract_voltage_levels,
    merge_duplicate_events,
    parse_french_datetime,
)


def test_parse_french_datetime_month_name() -> None:
    iso_value = parse_french_datetime("Incident du 14 février 2025 à 13h45")
    assert iso_value is not None
    assert iso_value.startswith("2025-02-14T13:45")


def test_extract_mw_kv_customers() -> None:
    text = "Perte de 35,5 MW sur ligne 225 kV avec 17 500 clients impactés."
    assert extract_mw_values(text) == [35.5]
    assert extract_voltage_levels(text) == [225]
    assert extract_customer_counts(text) == [17500]


def test_merge_duplicate_events_summary_and_min() -> None:
    events = [
        {
            "title": "MIN poste Lyon",
            "location": {"substation": "Lyon"},
            "start_time": "2025-01-20T10:00:00",
            "event_type": "outage",
            "page_numbers": [2],
            "actions_taken": ["A"],
            "raw_evidence": [{"page": 2, "text": "summary"}],
            "confidence": 0.4,
            "status": "unknown",
            "end_time": None,
        },
        {
            "title": "MIN poste Lyon",
            "location": {"substation": "Lyon"},
            "start_time": "2025-01-20T10:00:00",
            "event_type": "outage",
            "page_numbers": [7],
            "actions_taken": ["B"],
            "raw_evidence": [{"page": 7, "text": "detail"}],
            "confidence": 0.8,
            "status": "closed",
            "end_time": "2025-01-20T11:00:00",
        },
    ]
    merged = merge_duplicate_events(events)
    assert len(merged) == 1
    assert merged[0]["page_numbers"] == [2, 7]
    assert merged[0]["status"] == "closed"
    assert merged[0]["confidence"] == 0.8
