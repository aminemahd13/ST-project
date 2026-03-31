from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional

from app.config.settings import settings
from app.models.pipeline_models import UploadedDocumentInput
from app.orchestrator.orchestrator import Orchestrator
from app.repositories.pipeline_repository import PipelineRepository


StageCallback = Callable[
    [str, str, str, Optional[dict], Optional[str], int],
    Awaitable[None],
]


class JobProcessor:
    """In-process async worker for queued analysis jobs."""

    def __init__(
        self,
        repository: PipelineRepository,
        orchestrator: Orchestrator,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.repository = repository
        self.orchestrator = orchestrator
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)
        self.tasks: Dict[str, asyncio.Task[None]] = {}

    def submit(self, job_id: str, upload_input: UploadedDocumentInput) -> None:
        if job_id in self.tasks and not self.tasks[job_id].done():
            return
        task = asyncio.create_task(self._run_job(job_id, upload_input))
        self.tasks[job_id] = task

    async def _run_job(self, job_id: str, upload_input: UploadedDocumentInput) -> None:
        async with self.semaphore:
            last_error = "unknown error"
            for attempt in range(1, settings.job_max_retries + 1):
                await self.repository.mark_job_running(job_id)
                try:
                    result = await asyncio.wait_for(
                        self.orchestrator.process_document(
                            upload_input,
                            stage_callback=lambda stage_name, stage_status, payload=None, error=None: self._record_stage(
                                job_id=job_id,
                                stage_name=stage_name,
                                status=stage_status,
                                payload=payload,
                                error_message=error,
                                attempt=attempt,
                            ),
                        ),
                        timeout=settings.job_timeout_seconds,
                    )
                    payload = result.model_dump(mode="json")
                    if result.status == "failed":
                        last_error = "; ".join(result.errors) if result.errors else "pipeline failed"
                        await self.repository.mark_job_failed(
                            job_id=job_id,
                            error_message=last_error,
                            pipeline=payload,
                        )
                        return

                    analysis_stage = payload.get("analysis") or {}
                    markdown = analysis_stage.get("human_summary")
                    await self.repository.mark_job_completed(
                        job_id=job_id,
                        pipeline=payload,
                        analysis_markdown=markdown,
                        status=result.status,
                    )
                    return
                except TimeoutError:
                    last_error = f"job timed out after {settings.job_timeout_seconds:.0f}s"
                    self.logger.exception("Job timed out", extra={"job_id": job_id, "attempt": attempt})
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    self.logger.exception("Job execution failed", extra={"job_id": job_id, "attempt": attempt})

            await self.repository.mark_job_failed(job_id, last_error)

    async def _record_stage(
        self,
        *,
        job_id: str,
        stage_name: str,
        status: str,
        payload: Optional[dict],
        error_message: Optional[str],
        attempt: int,
    ) -> None:
        await self.repository.upsert_stage(
            job_id=job_id,
            stage_name=stage_name,
            status=status,
            attempt=attempt,
            payload=payload,
            error_message=error_message,
        )
