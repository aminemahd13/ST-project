from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from app.agents.analysis_agent import AnalysisAgent
from app.agents.collector_agent import CollectorAgent
from app.agents.incident_agent import IncidentAgent
from app.agents.preprocessing_agent import PreprocessingAgent
from app.models.pipeline_models import PipelineResult, UploadedDocumentInput
from app.repositories.pipeline_repository import PipelineRepository


class Orchestrator:
    """Coordinates the end-to-end processing of incoming logs via the agent pipeline."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.repository = PipelineRepository()
        self.collector = CollectorAgent(name="collector", repository=self.repository)
        self.preprocessing = PreprocessingAgent(name="preprocessing", repository=self.repository)
        self.incident = IncidentAgent(name="incident", repository=self.repository)
        self.analysis = AnalysisAgent(name="analysis", repository=self.repository)

    async def process_document(
        self,
        upload_input: UploadedDocumentInput,
        stage_callback: Optional[
            Callable[[str, str, Optional[Dict[str, Any]], Optional[str]], Awaitable[None]]
        ] = None,
    ) -> PipelineResult:
        """Run collector -> preprocessing -> incident -> analysis with partial-failure support."""
        errors = []
        document_id: Optional[str] = None
        collector_output: Optional[Dict[str, Any]] = None
        preprocessing_output: Optional[Dict[str, Any]] = None
        incident_output: Optional[Dict[str, Any]] = None
        analysis_output: Optional[Dict[str, Any]] = None

        async def emit_stage(
            stage_name: str,
            status: str,
            payload: Optional[Dict[str, Any]] = None,
            error: Optional[str] = None,
        ) -> None:
            if stage_callback:
                await stage_callback(stage_name, status, payload, error)

        try:
            self.logger.info("Stage collector started", extra={"upload_filename": upload_input.filename})
            await emit_stage("collector", "running")
            collected = await self.collector.run(upload_input)
            document_id = collected.document_id
            collector_output = collected.model_dump(mode="json")
            await emit_stage("collector", "completed", collector_output)
            self.logger.info("Stage collector completed", extra={"document_id": document_id})
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Collector failed")
            errors.append(f"collector: {exc}")
            await emit_stage("collector", "failed", collector_output, str(exc))
            return PipelineResult(
                document_id=document_id,
                status="failed",
                collector=collector_output,
                preprocessing=preprocessing_output,
                incident=incident_output,
                analysis=analysis_output,
                errors=errors,
            )

        try:
            self.logger.info("Stage preprocessing started", extra={"document_id": document_id})
            await emit_stage("preprocessing", "running")
            preprocessed = await self.preprocessing.run(collected)
            preprocessing_output = preprocessed.model_dump(mode="json")
            await emit_stage("preprocessing", "completed", preprocessing_output)
            self.logger.info("Stage preprocessing completed", extra={"document_id": document_id})
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Preprocessing failed")
            errors.append(f"preprocessing: {exc}")
            await emit_stage("preprocessing", "failed", preprocessing_output, str(exc))
            return PipelineResult(
                document_id=document_id,
                status="partial",
                collector=collector_output,
                preprocessing=preprocessing_output,
                incident=incident_output,
                analysis=analysis_output,
                errors=errors,
            )

        try:
            self.logger.info("Stage incident started", extra={"document_id": document_id})
            await emit_stage("incident", "running")
            incident_stage = await self.incident.run(preprocessed)
            incident_output = incident_stage.model_dump(mode="json")
            await emit_stage("incident", "completed", incident_output)
            self.logger.info("Stage incident completed", extra={"document_id": document_id})
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Incident stage failed")
            errors.append(f"incident: {exc}")
            await emit_stage("incident", "failed", incident_output, str(exc))
            return PipelineResult(
                document_id=document_id,
                status="partial",
                collector=collector_output,
                preprocessing=preprocessing_output,
                incident=incident_output,
                analysis=analysis_output,
                errors=errors,
            )

        try:
            self.logger.info("Stage analysis started", extra={"document_id": document_id})
            await emit_stage("analysis", "running")
            analysis_stage = await self.analysis.run(incident_stage)
            analysis_output = analysis_stage.model_dump(mode="json")
            await emit_stage("analysis", "completed", analysis_output)
            self.logger.info("Stage analysis completed", extra={"document_id": document_id})
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Analysis failed")
            errors.append(f"analysis: {exc}")
            failure_payload = analysis_output
            trace = getattr(exc, "trace", None)
            if isinstance(trace, dict):
                failure_payload = {"llm_trace": trace}
            await emit_stage("analysis", "failed", failure_payload, str(exc))
            return PipelineResult(
                document_id=document_id,
                status="failed",
                collector=collector_output,
                preprocessing=preprocessing_output,
                incident=incident_output,
                analysis=analysis_output,
                errors=errors,
            )

        status = "completed" if not errors else "partial"
        return PipelineResult(
            document_id=document_id,
            status=status,
            collector=collector_output,
            preprocessing=preprocessing_output,
            incident=incident_output,
            analysis=analysis_output,
            errors=errors,
        )

