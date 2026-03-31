from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


PipelineStatus = Literal["completed", "partial", "failed"]
JobStatus = Literal["queued", "running", "completed", "partial", "failed"]


class UploadedDocumentInput(BaseModel):
    """Input payload for the PDF processing pipeline."""

    file_path: str
    filename: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RawPage(BaseModel):
    page_number: int
    raw_text: str
    extraction_method: str = "pypdf"
    needs_fallback: bool = False


class CollectorOutput(BaseModel):
    document_id: str
    file_path: str
    filename: str
    sha256: str
    page_count: int
    raw_pages: List[RawPage] = Field(default_factory=list)
    ingestion_timestamp: datetime


class StructuredDocumentOutput(BaseModel):
    document_id: str
    source_file: str
    report: Dict[str, Any]
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    events: List[Dict[str, Any]] = Field(default_factory=list)


class IncidentStageOutput(BaseModel):
    document_id: str
    incidents: List[Dict[str, Any]] = Field(default_factory=list)
    priority_queue: List[Dict[str, Any]] = Field(default_factory=list)


class AnalysisStageOutput(BaseModel):
    document_id: str
    analysis: Dict[str, Any]
    human_summary: str


class PipelineResult(BaseModel):
    document_id: Optional[str] = None
    status: PipelineStatus
    collector: Optional[Dict[str, Any]] = None
    preprocessing: Optional[Dict[str, Any]] = None
    incident: Optional[Dict[str, Any]] = None
    analysis: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)


class StageSnapshot(BaseModel):
    stage_name: str
    status: str
    attempt: int = 1
    error_message: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None


class JobSubmissionResponse(BaseModel):
    job_id: str
    status: JobStatus
    status_url: str
    deduplicated: bool = False
    force_refresh_applied: bool = False
    created_at: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    filename: str
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    deduplicated_from_job_id: Optional[str] = None
    error_message: Optional[str] = None
    analysis: Optional[str] = None
    model: str = "pipeline-v2"
    pipeline: Optional[Dict[str, Any]] = None
    stages: List[StageSnapshot] = Field(default_factory=list)
