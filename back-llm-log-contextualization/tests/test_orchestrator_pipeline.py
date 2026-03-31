import asyncio
import logging

from app.models.pipeline_models import (
    AnalysisStageOutput,
    CollectorOutput,
    IncidentStageOutput,
    PipelineResult,
    RawPage,
    StructuredDocumentOutput,
    UploadedDocumentInput,
)
from app.orchestrator.orchestrator import Orchestrator


class DummyCollector:
    async def run(self, _: UploadedDocumentInput) -> CollectorOutput:
        return CollectorOutput(
            document_id="doc-1",
            file_path="/tmp/a.pdf",
            filename="a.pdf",
            sha256="abc",
            page_count=1,
            raw_pages=[RawPage(page_number=1, raw_text="Incident", needs_fallback=False)],
            ingestion_timestamp="2025-01-01T00:00:00Z",
        )


class DummyPreprocessing:
    async def run(self, _: CollectorOutput) -> StructuredDocumentOutput:
        return StructuredDocumentOutput(
            document_id="doc-1",
            source_file="a.pdf",
            report={"title": "Synthese", "report_date": "2025-01-01"},
            sections=[],
            events=[],
        )


class DummyIncident:
    async def run(self, _: StructuredDocumentOutput) -> IncidentStageOutput:
        return IncidentStageOutput(document_id="doc-1", incidents=[], priority_queue=[])


class DummyAnalysis:
    async def run(self, _: IncidentStageOutput) -> AnalysisStageOutput:
        return AnalysisStageOutput(
            document_id="doc-1",
            analysis={"executive_summary": "ok"},
            human_summary="# ok",
        )


def test_orchestrator_happy_path() -> None:
    orchestrator = Orchestrator()
    orchestrator.collector = DummyCollector()
    orchestrator.preprocessing = DummyPreprocessing()
    orchestrator.incident = DummyIncident()
    orchestrator.analysis = DummyAnalysis()

    payload = UploadedDocumentInput(file_path="/tmp/a.pdf", filename="a.pdf")
    result = asyncio.run(orchestrator.process_document(payload))
    assert isinstance(result, PipelineResult)
    assert result.document_id == "doc-1"
    assert result.status == "completed"
    assert result.analysis is not None


def test_orchestrator_happy_path_with_info_logging(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.orchestrator.orchestrator")

    orchestrator = Orchestrator()
    orchestrator.collector = DummyCollector()
    orchestrator.preprocessing = DummyPreprocessing()
    orchestrator.incident = DummyIncident()
    orchestrator.analysis = DummyAnalysis()

    payload = UploadedDocumentInput(file_path="/tmp/a.pdf", filename="a.pdf")
    result = asyncio.run(orchestrator.process_document(payload))

    assert result.status == "completed"
