from app.agents.incident_agent import IncidentAgent
from app.repositories.pipeline_repository import PipelineRepository


def _event(customers: int, mw: float, title: str) -> dict:
    return {
        "title": title,
        "event_type": "outage",
        "impact": {"customers_affected": customers, "mw_lost": mw},
        "actions_taken": [],
        "cause": {"description": ""},
        "media_relevance": "none",
    }


def test_classify_critical_by_customers() -> None:
    agent = IncidentAgent(name="incident", repository=PipelineRepository())
    severity = agent._classify_severity(_event(60000, 10.0, "Perte majeure"))  # noqa: SLF001
    assert severity == "critical"


def test_classify_high_by_mw() -> None:
    agent = IncidentAgent(name="incident", repository=PipelineRepository())
    severity = agent._classify_severity(_event(1000, 35.0, "Incident local"))  # noqa: SLF001
    assert severity == "high"


def test_assign_tags_for_media_and_telecom() -> None:
    agent = IncidentAgent(name="incident", repository=PipelineRepository())
    event = _event(500, 1.0, "Perte telecom supervision")
    event["media_relevance"] = "potential"
    tags = agent._extract_tags(event)  # noqa: SLF001
    assert "customer_outage" in tags
    assert "telecom_loss" in tags
    assert "media_sensitive" in tags
