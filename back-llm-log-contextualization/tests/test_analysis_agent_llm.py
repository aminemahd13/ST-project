import asyncio
import json
import pytest

from app.agents.analysis_agent import AnalysisAgent
from app.models.pipeline_models import IncidentStageOutput
from app.repositories.pipeline_repository import PipelineRepository


class DummyLLM:
    model = "dummy"

    async def generate(self, *_args, **_kwargs) -> str:
        return ""

    async def generate_with_diagnostics(self, *_args, **_kwargs) -> dict:
        return {
            "provider": "dummy",
            "model": "dummy",
            "latency_ms": 1.0,
            "output": "",
            "error": "disabled",
            "response_chars": 0,
            "ok": False,
        }


class DummyRetriever:
    async def retrieve(self, _query: str, top_k: int = 5) -> list[dict]:  # noqa: ARG002
        return []


class DummyRepository:
    async def save_analysis(self, _analysis: dict) -> None:
        return None


class DummyLLMNonCanonical:
    model = "dummy"

    async def generate_with_diagnostics(self, *_args, **_kwargs) -> dict:
        payload = {
            "executive_summary": "Grid incidents occurred across equipment and telecom domains.",
            "cross_incident_insights": [
                {"type": "Weather", "details": ["Storm conditions contributed to multiple disturbances."]}
            ],
            "recommended_actions": [
                {"type": "Operations", "details": ["Pre-position mobile teams."]},
                "Validate protection settings on impacted corridors.",
            ],
            "reasoning_summary": "- Several events share timing and cause patterns.\n- Evidence quality varies by page.",
            "human_summary_markdown": "# Incident Summary",
        }
        return {
            "provider": "huggingface",
            "model": "dummy:model",
            "latency_ms": 12.0,
            "output": json.dumps(payload),
            "error": None,
            "response_chars": 320,
            "ok": True,
        }


class DummyLLMGeneric:
    model = "dummy"

    async def generate_with_diagnostics(self, *_args, **_kwargs) -> dict:
        payload = {
            "executive_summary": "The grid experienced several incidents.",
            "cross_incident_insights": [],
            "recommended_actions": [],
            "reasoning_summary": [],
            "human_summary_markdown": "# short",
        }
        return {
            "provider": "huggingface",
            "model": "dummy:model",
            "latency_ms": 12.0,
            "output": json.dumps(payload),
            "error": None,
            "response_chars": 220,
            "ok": True,
        }


def test_analysis_agent_requires_llm_output() -> None:
    agent = AnalysisAgent(
        name="analysis",
        repository=PipelineRepository(),
        llm_service=DummyLLM(),
        retriever=DummyRetriever(),
    )
    payload = IncidentStageOutput(
        document_id="doc-1",
        incidents=[
            {
                "title": "Incident poste Lyon",
                "severity": "high",
                "event_type": "outage",
                "impact": {"customers_affected": 2000, "mw_lost": 15},
                "cause": {"category": "equipment_fault"},
                "assets": [{"asset_type": "line", "name": "L1"}],
                "tags": ["customer_outage"],
                "status": "closed",
                "confidence": 0.8,
            }
        ],
        priority_queue=[],
    )
    with pytest.raises(RuntimeError, match="LLM response is empty"):
        asyncio.run(agent.run(payload))


def test_analysis_agent_normalizes_noncanonical_llm_shapes() -> None:
    agent = AnalysisAgent(
        name="analysis",
        repository=DummyRepository(),
        llm_service=DummyLLMNonCanonical(),
        retriever=DummyRetriever(),
    )
    payload = IncidentStageOutput(
        document_id="doc-2",
        incidents=[
            {
                "title": "Incident poste Lille",
                "severity": "high",
                "event_type": "outage",
                "impact": {"customers_affected": 1200, "mw_lost": 22},
                "cause": {"category": "weather"},
                "assets": [{"asset_type": "line", "name": "L2"}],
                "tags": ["telecom_loss"],
                "status": "closed",
                "confidence": 0.7,
            }
        ],
        priority_queue=[],
    )

    result = asyncio.run(agent.run(payload))
    assert result.analysis["cross_incident_insights"]
    assert result.analysis["recommended_actions"]
    assert result.analysis["reasoning_summary"]
    assert "## Key Statistics" in result.human_summary
    assert "## Recommended Actions" in result.human_summary


def test_analysis_agent_quality_gate_upgrades_generic_llm_output() -> None:
    agent = AnalysisAgent(
        name="analysis",
        repository=DummyRepository(),
        llm_service=DummyLLMGeneric(),
        retriever=DummyRetriever(),
    )
    payload = IncidentStageOutput(
        document_id="doc-3",
        incidents=[
            {
                "title": "Incident poste Lille",
                "severity": "high",
                "event_type": "outage",
                "impact": {"customers_affected": 1200, "mw_lost": 22, "duration_minutes": 40},
                "cause": {"category": "weather"},
                "assets": [{"asset_type": "line", "name": "L2"}],
                "tags": ["telecom_loss"],
                "status": "closed",
                "confidence": 0.7,
                "region": "Nord",
            },
            {
                "title": "Incident poste Avelin",
                "severity": "high",
                "event_type": "equipment_fault",
                "impact": {"customers_affected": 0, "mw_lost": 31, "duration_minutes": 80},
                "cause": {"category": "equipment_fault"},
                "assets": [{"asset_type": "transformer", "name": "TR-3"}],
                "tags": ["customer_outage"],
                "status": "unknown",
                "confidence": 0.45,
                "region": "Nord",
            },
        ],
        priority_queue=[],
    )

    result = asyncio.run(agent.run(payload))
    assert "incidents identified" in result.analysis["executive_summary"].lower()
    assert "## Patterns" in result.human_summary
    assert result.analysis["cross_incident_insights"]
    assert result.analysis["recommended_actions"]
    assert result.analysis["reasoning_summary"]
