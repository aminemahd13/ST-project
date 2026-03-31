from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import Select, desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.db import get_session_factory
from app.database.models import Job, JobArtifact, JobStage


STAGE_ORDER = {
    "collector": 0,
    "preprocessing": 1,
    "incident": 2,
    "analysis": 3,
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PipelineRepository:
    """SQL-backed persistence abstraction for pipeline artifacts and job lifecycle."""

    _schema_initialized = False

    def __init__(self, session_factory: Optional[async_sessionmaker[AsyncSession]] = None) -> None:
        self.session_factory = session_factory or get_session_factory()

    async def create_job(
        self,
        *,
        filename: str,
        storage_path: str,
        sha256: str,
        size_bytes: int,
    ) -> str:
        await self._ensure_schema()
        job_id = str(uuid4())
        async with self.session_factory() as session:
            job = Job(
                id=job_id,
                filename=filename,
                storage_path=storage_path,
                sha256=sha256,
                status="queued",
                size_bytes=size_bytes,
            )
            session.add(job)
            await session.commit()
        return job_id

    async def find_latest_job_by_sha256(self, sha256: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        stmt: Select[tuple[Job]] = (
            select(Job)
            .where(Job.sha256 == sha256)
            .order_by(desc(Job.created_at))
            .limit(1)
        )
        async with self.session_factory() as session:
            job = (await session.execute(stmt)).scalar_one_or_none()
            if not job:
                return None
            return self._job_to_dict(job)

    async def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if not job:
                return None
            payload = self._job_to_dict(job)
            payload["stages"] = await self._get_stages_for_job(session, job_id)
            return payload

    async def mark_job_running(self, job_id: str) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            if job.started_at is None:
                job.started_at = utcnow()
            job.status = "running"
            job.updated_at = utcnow()
            await session.commit()

    async def mark_job_completed(
        self,
        *,
        job_id: str,
        pipeline: Dict[str, Any],
        analysis_markdown: Optional[str],
        status: str = "completed",
    ) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            job.status = status
            job.pipeline_json = pipeline
            job.analysis_markdown = analysis_markdown
            job.result_json = {
                "id": job.id,
                "filename": job.filename,
                "analysis": analysis_markdown,
                "timestamp": utcnow().isoformat(),
                "model": job.model,
                "pipeline": pipeline,
            }
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            await session.commit()

    async def mark_job_failed(self, job_id: str, error_message: str, pipeline: Optional[Dict[str, Any]] = None) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if not job:
                return
            job.status = "failed"
            job.error_message = error_message[:4000]
            job.pipeline_json = pipeline
            job.finished_at = utcnow()
            job.updated_at = utcnow()
            await session.commit()

    async def link_deduplicated_job(self, *, job_id: str, source_job_id: str) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            source_job = await session.get(Job, source_job_id)
            if not job or not source_job:
                return
            job.deduplicated_from_job_id = source_job_id
            job.status = source_job.status
            job.pipeline_json = source_job.pipeline_json
            job.result_json = source_job.result_json
            job.analysis_markdown = source_job.analysis_markdown
            job.error_message = source_job.error_message
            job.started_at = source_job.started_at
            job.finished_at = source_job.finished_at
            job.updated_at = utcnow()
            await session.commit()

    async def upsert_stage(
        self,
        *,
        job_id: str,
        stage_name: str,
        status: str,
        attempt: int = 1,
        payload: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            stmt: Select[tuple[JobStage]] = (
                select(JobStage)
                .where(
                    JobStage.job_id == job_id,
                    JobStage.stage_name == stage_name,
                    JobStage.attempt == attempt,
                )
                .limit(1)
            )
            stage = (await session.execute(stmt)).scalar_one_or_none()
            if stage is None:
                stage = JobStage(
                    job_id=job_id,
                    stage_name=stage_name,
                    attempt=attempt,
                    status=status,
                    order_index=STAGE_ORDER.get(stage_name, 99),
                )
                session.add(stage)

            if status == "running" and stage.started_at is None:
                stage.started_at = utcnow()
            if status in {"completed", "failed"}:
                stage.finished_at = utcnow()
            stage.status = status
            stage.updated_at = utcnow()
            if payload is not None:
                stage.payload_json = payload
            if error_message:
                stage.error_message = error_message[:4000]
            await session.commit()

    async def get_stages(self, job_id: str) -> List[Dict[str, Any]]:
        await self._ensure_schema()
        async with self.session_factory() as session:
            return await self._get_stages_for_job(session, job_id)

    async def save_artifact(self, job_id: str, artifact_type: str, payload: Dict[str, Any]) -> None:
        await self._ensure_schema()
        async with self.session_factory() as session:
            artifact = JobArtifact(
                job_id=job_id,
                artifact_type=artifact_type,
                payload_json=payload,
            )
            session.add(artifact)
            await session.commit()

    async def get_artifacts(self, job_id: str) -> List[Dict[str, Any]]:
        await self._ensure_schema()
        stmt: Select[tuple[JobArtifact]] = (
            select(JobArtifact)
            .where(JobArtifact.job_id == job_id)
            .order_by(JobArtifact.id.asc())
        )
        async with self.session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "artifact_type": row.artifact_type,
                    "payload": row.payload_json,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ]

    async def save_raw_document(self, document: Dict[str, Any]) -> None:
        await self.save_artifact(document["document_id"], "collector.raw_document", document)

    async def save_raw_pages(self, document_id: str, pages: List[Dict[str, Any]]) -> None:
        await self.save_artifact(document_id, "collector.raw_pages", {"pages": pages})

    async def save_structured_document(self, document: Dict[str, Any]) -> None:
        await self.save_artifact(document["document_id"], "preprocessing.structured_document", document)

    async def save_incidents(self, document_id: str, incidents: List[Dict[str, Any]]) -> None:
        await self.save_artifact(document_id, "incident.incidents", {"incidents": incidents})

    async def save_analysis(self, analysis: Dict[str, Any]) -> None:
        await self.save_artifact(analysis["document_id"], "analysis.result", analysis)

    async def _get_stages_for_job(self, session: AsyncSession, job_id: str) -> List[Dict[str, Any]]:
        stmt: Select[tuple[JobStage]] = (
            select(JobStage)
            .where(JobStage.job_id == job_id)
            .order_by(JobStage.order_index.asc(), JobStage.id.asc())
        )
        stages = (await session.execute(stmt)).scalars().all()
        return [
            {
                "stage_name": stage.stage_name,
                "status": stage.status,
                "attempt": stage.attempt,
                "error_message": stage.error_message,
                "payload": stage.payload_json,
                "started_at": stage.started_at.isoformat() if stage.started_at else None,
                "finished_at": stage.finished_at.isoformat() if stage.finished_at else None,
                "updated_at": stage.updated_at.isoformat() if stage.updated_at else None,
            }
            for stage in stages
        ]

    def _job_to_dict(self, job: Job) -> Dict[str, Any]:
        return {
            "id": job.id,
            "filename": job.filename,
            "storage_path": job.storage_path,
            "sha256": job.sha256,
            "status": job.status,
            "size_bytes": job.size_bytes,
            "model": job.model,
            "deduplicated_from_job_id": job.deduplicated_from_job_id,
            "error_message": job.error_message,
            "result": job.result_json,
            "pipeline": job.pipeline_json,
            "analysis": job.analysis_markdown,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }

    async def _ensure_schema(self) -> None:
        if self.__class__._schema_initialized:
            return
        from app.database.db import init_db

        await init_db()
        self.__class__._schema_initialized = True
