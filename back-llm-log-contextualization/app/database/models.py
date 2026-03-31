from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(260))
    storage_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="queued")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(120), default="pipeline-v2")
    deduplicated_from_job_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    pipeline_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    analysis_markdown: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list["JobStage"]] = relationship(back_populates="job", cascade="all, delete-orphan")
    artifacts: Mapped[list["JobArtifact"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobStage(Base):
    __tablename__ = "job_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    stage_name: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="stages")


class JobArtifact(Base):
    __tablename__ = "job_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="artifacts")
