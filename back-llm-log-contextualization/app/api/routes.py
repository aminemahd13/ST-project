from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status

from app.api.dependencies import enforce_api_key, enforce_rate_limit
from app.config.settings import settings
from app.models.pipeline_models import JobStatusResponse, JobSubmissionResponse, StageSnapshot, UploadedDocumentInput
from app.orchestrator.job_processor import JobProcessor
from app.orchestrator.orchestrator import Orchestrator
from app.repositories.pipeline_repository import PipelineRepository
from app.services.storage_service import StorageService


router = APIRouter()
_repository = PipelineRepository()
_orchestrator = Orchestrator()
_processor = JobProcessor(repository=_repository, orchestrator=_orchestrator)
_storage = StorageService()


def _validate_llm_configuration() -> None:
    provider = (settings.llm_provider or "auto").strip().lower()
    if provider == "huggingface" and not settings.hf_token.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "llm_misconfigured",
                "message": "GRID_APP_HF_TOKEN must be set when GRID_APP_LLM_PROVIDER=huggingface.",
            },
        )
    if provider == "ollama" and (
        not settings.ollama_base_url.strip() or not settings.ollama_model.strip()
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "llm_misconfigured",
                "message": (
                    "GRID_APP_OLLAMA_BASE_URL and GRID_APP_OLLAMA_MODEL must be set when "
                    "GRID_APP_LLM_PROVIDER=ollama."
                ),
            },
        )


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _finalize_stale_job_if_needed(job_id: str, job: dict) -> dict:
    if job.get("status") not in {"queued", "running"}:
        return job
    updated_at = _parse_iso_datetime(job.get("updated_at"))
    max_runtime_seconds = int(settings.job_timeout_seconds * settings.job_max_retries) + 30
    no_stage_update_seconds = 45
    stages = job.get("stages") or []
    if (
        job.get("status") == "running"
        and not stages
        and updated_at is not None
        and int((datetime.now(timezone.utc) - updated_at).total_seconds()) > no_stage_update_seconds
    ):
        task = _processor.tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
        await _repository.mark_job_failed(
            job_id=job_id,
            error_message=(
                "Job is running but no pipeline stage updates were recorded. "
                "Worker task was cancelled."
            ),
            pipeline=job.get("pipeline"),
        )
        refreshed = await _repository.get_job(job_id)
        return refreshed or job

    task = _processor.tasks.get(job_id)
    if task is not None:
        if not task.done():
            if updated_at is None:
                return job
            age_seconds = int((datetime.now(timezone.utc) - updated_at).total_seconds())
            if age_seconds <= max_runtime_seconds:
                return job
            task.cancel()
            await _repository.mark_job_failed(
                job_id=job_id,
                error_message=(
                    "Job exceeded expected runtime while task was still running. "
                    "Task was cancelled."
                ),
                pipeline=job.get("pipeline"),
            )
            refreshed = await _repository.get_job(job_id)
            return refreshed or job
        if task.cancelled():
            reason = "Background task was cancelled before completion."
        else:
            task_error = task.exception()
            reason = (
                f"Background task crashed before completion: {task_error}"
                if task_error
                else "Background task ended without writing final job status."
            )
        await _repository.mark_job_failed(
            job_id=job_id,
            error_message=reason,
            pipeline=job.get("pipeline"),
        )
        refreshed = await _repository.get_job(job_id)
        return refreshed or job

    if updated_at is None:
        return job

    age_seconds = int((datetime.now(timezone.utc) - updated_at).total_seconds())
    if age_seconds <= max_runtime_seconds:
        return job

    await _repository.mark_job_failed(
        job_id=job_id,
        error_message="Job appears orphaned while still marked running. Worker may have restarted.",
        pipeline=job.get("pipeline"),
    )
    refreshed = await _repository.get_job(job_id)
    return refreshed or job


def _validate_pdf_upload(filename: str, content_type: str | None, content: bytes) -> None:
    extension = Path(filename).suffix.lower()
    if extension not in settings.allowed_upload_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_file_extension",
                "message": f"Only {settings.allowed_upload_extensions} files are accepted.",
            },
        )
    if content_type and "pdf" not in content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_content_type",
                "message": "Uploaded content type must be PDF.",
            },
        )
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "invalid_pdf_signature",
                "message": "File does not contain a valid PDF signature.",
            },
        )


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


@router.post(
    "/analyze",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobSubmissionResponse,
    summary="Queue a PDF for asynchronous analysis",
)
async def analyze_file(
    request: Request,
    file: UploadFile = File(...),
    force_refresh: bool = Form(False),
    _: None = Depends(enforce_api_key),
    __: None = Depends(enforce_rate_limit),
) -> JobSubmissionResponse:
    _validate_llm_configuration()
    filename = file.filename or "upload.pdf"
    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "empty_file", "message": "Uploaded file is empty."},
        )
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "file_too_large",
                "message": f"Maximum allowed upload size is {settings.max_upload_size_bytes} bytes.",
            },
        )

    _validate_pdf_upload(filename, file.content_type, content)

    force_refresh_requested = force_refresh or _is_truthy(request.query_params.get("force_refresh")) or _is_truthy(
        request.headers.get("x-force-refresh")
    )

    sha256 = hashlib.sha256(content).hexdigest()
    storage_path = _storage.save_upload(content, filename, sha256)
    existing = None if force_refresh_requested else await _repository.find_latest_job_by_sha256(sha256)
    job_id = await _repository.create_job(
        filename=filename,
        storage_path=storage_path,
        sha256=sha256,
        size_bytes=len(content),
    )

    deduplicated = False
    if existing and existing["status"] in {"completed", "partial"}:
        await _repository.link_deduplicated_job(job_id=job_id, source_job_id=existing["id"])
        deduplicated = True
    else:
        payload = UploadedDocumentInput(
            file_path=storage_path,
            filename=filename,
            metadata={
                "content_type": file.content_type,
                "size_bytes": len(content),
                "sha256": sha256,
                "job_id": job_id,
                "force_refresh": force_refresh_requested,
            },
        )
        _processor.submit(job_id, payload)

    created_at = datetime.now(timezone.utc).isoformat()
    return JobSubmissionResponse(
        job_id=job_id,
        status="completed" if deduplicated else "queued",
        status_url=f"/api/jobs/{job_id}",
        deduplicated=deduplicated,
        force_refresh_applied=force_refresh_requested,
        created_at=created_at,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get analysis job status and result payload",
)
async def get_job_status(
    job_id: str,
    _: None = Depends(enforce_api_key),
    __: None = Depends(enforce_rate_limit),
) -> JobStatusResponse:
    job = await _repository.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "job_not_found", "message": f"Job {job_id} does not exist."},
        )
    job = await _finalize_stale_job_if_needed(job_id, job)

    stage_items = [StageSnapshot(**stage) for stage in job.get("stages", [])]
    status_value = job.get("status") or "failed"
    if status_value not in {"queued", "running", "completed", "partial", "failed"}:
        status_value = "failed"

    return JobStatusResponse(
        job_id=job["id"],
        status=status_value,
        filename=job["filename"],
        created_at=job["created_at"] or "",
        updated_at=job["updated_at"] or "",
        started_at=job.get("started_at"),
        finished_at=job.get("finished_at"),
        deduplicated_from_job_id=job.get("deduplicated_from_job_id"),
        error_message=job.get("error_message"),
        analysis=job.get("analysis"),
        model=job.get("model") or "pipeline-v2",
        pipeline=job.get("pipeline"),
        stages=stage_items,
    )


@router.get("/health", summary="Health check")
async def healthcheck() -> dict:
    return {"status": "ok"}
