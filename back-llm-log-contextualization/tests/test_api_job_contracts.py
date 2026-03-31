import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import create_app


def test_analyze_rejects_non_pdf() -> None:
    app = create_app()
    client = TestClient(app)
    response = client.post(
        "/api/analyze",
        files={"file": ("not_pdf.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["detail"]["error"] in {"invalid_file_extension", "invalid_content_type"}


def test_analyze_returns_job_id(monkeypatch) -> None:
    from app.api import routes

    app = create_app()
    client = TestClient(app)

    async def fake_find_latest(_sha256: str) -> None:
        return None

    async def fake_create_job(**_kwargs) -> str:
        return "job-test-1"

    monkeypatch.setattr(routes._repository, "find_latest_job_by_sha256", fake_find_latest)  # noqa: SLF001
    monkeypatch.setattr(routes._repository, "create_job", fake_create_job)  # noqa: SLF001
    monkeypatch.setattr(routes._processor, "submit", lambda *_args, **_kwargs: None)  # noqa: SLF001

    response = client.post(
        "/api/analyze",
        files={"file": ("sample.pdf", b"%PDF-1.4\n%minimal", "application/pdf")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status_url"].startswith("/api/jobs/")


def test_analyze_rejects_when_huggingface_token_missing(monkeypatch) -> None:
    from app.api import routes

    app = create_app()
    client = TestClient(app)
    monkeypatch.setattr(routes.settings, "llm_provider", "huggingface")  # noqa: SLF001
    monkeypatch.setattr(routes.settings, "hf_token", "")  # noqa: SLF001

    response = client.post(
        "/api/analyze",
        files={"file": ("sample.pdf", b"%PDF-1.4\n%minimal", "application/pdf")},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["detail"]["error"] == "llm_misconfigured"


def test_analyze_force_refresh_bypasses_dedup(monkeypatch) -> None:
    from app.api import routes

    app = create_app()
    client = TestClient(app)
    submitted_jobs: list[str] = []
    dedup_linked = {"value": False}

    async def fake_find_latest(_sha256: str) -> dict:
        return {"id": "existing-job", "status": "completed"}

    async def fake_create_job(**_kwargs) -> str:
        return "job-test-2"

    async def fake_link_deduplicated_job(*, job_id: str, source_job_id: str) -> None:
        dedup_linked["value"] = True

    monkeypatch.setattr(routes._repository, "find_latest_job_by_sha256", fake_find_latest)  # noqa: SLF001
    monkeypatch.setattr(routes._repository, "create_job", fake_create_job)  # noqa: SLF001
    monkeypatch.setattr(routes._repository, "link_deduplicated_job", fake_link_deduplicated_job)  # noqa: SLF001
    monkeypatch.setattr(
        routes._processor,
        "submit",
        lambda job_id, _payload: submitted_jobs.append(job_id),
    )  # noqa: SLF001

    response = client.post(
        "/api/analyze",
        data={"force_refresh": "true"},
        files={"file": ("sample.pdf", b"%PDF-1.4\n%minimal", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["deduplicated"] is False
    assert body["force_refresh_applied"] is True
    assert body["status"] == "queued"
    assert dedup_linked["value"] is False
    assert submitted_jobs


def test_analyze_force_refresh_header_bypasses_dedup(monkeypatch) -> None:
    from app.api import routes

    app = create_app()
    client = TestClient(app)
    submitted_jobs: list[str] = []

    async def fake_find_latest(_sha256: str) -> dict:
        return {"id": "existing-job", "status": "completed"}

    async def fake_create_job(**_kwargs) -> str:
        return "job-test-3"

    monkeypatch.setattr(routes._repository, "find_latest_job_by_sha256", fake_find_latest)  # noqa: SLF001
    monkeypatch.setattr(routes._repository, "create_job", fake_create_job)  # noqa: SLF001
    monkeypatch.setattr(
        routes._processor,
        "submit",
        lambda job_id, _payload: submitted_jobs.append(job_id),
    )  # noqa: SLF001

    response = client.post(
        "/api/analyze",
        headers={"x-force-refresh": "1"},
        files={"file": ("sample.pdf", b"%PDF-1.4\n%minimal", "application/pdf")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["deduplicated"] is False
    assert body["force_refresh_applied"] is True
    assert submitted_jobs


def test_finalize_stale_job_when_background_task_crashed(monkeypatch) -> None:
    from app.api import routes

    failed_calls: list[dict] = []

    class FakeRepository:
        async def mark_job_failed(self, **kwargs) -> None:  # noqa: ANN003
            failed_calls.append(kwargs)

        async def get_job(self, job_id: str) -> dict:  # noqa: ARG002
            return {"status": "failed", "id": "job-1"}

    class FakeTask:
        def done(self) -> bool:
            return True

        def cancelled(self) -> bool:
            return False

        def exception(self) -> Exception:
            return RuntimeError("boom")

    monkeypatch.setattr(routes, "_repository", FakeRepository())
    monkeypatch.setattr(routes._processor, "tasks", {"job-1": FakeTask()})  # noqa: SLF001

    job = {
        "status": "running",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"analysis": None},
    }
    result = asyncio.run(routes._finalize_stale_job_if_needed("job-1", job))  # noqa: SLF001

    assert failed_calls
    assert "crashed" in failed_calls[0]["error_message"].lower()
    assert result["status"] == "failed"


def test_finalize_stale_job_cancels_long_running_task(monkeypatch) -> None:
    from app.api import routes

    failed_calls: list[dict] = []
    cancelled = {"value": False}

    class FakeRepository:
        async def mark_job_failed(self, **kwargs) -> None:  # noqa: ANN003
            failed_calls.append(kwargs)

        async def get_job(self, job_id: str) -> dict:  # noqa: ARG002
            return {"status": "failed", "id": "job-3"}

    class FakeTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            cancelled["value"] = True

    monkeypatch.setattr(routes, "_repository", FakeRepository())
    monkeypatch.setattr(routes._processor, "tasks", {"job-3": FakeTask()})  # noqa: SLF001

    old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    job = {
        "status": "running",
        "updated_at": old_time,
        "pipeline": {"analysis": None},
    }
    result = asyncio.run(routes._finalize_stale_job_if_needed("job-3", job))  # noqa: SLF001

    assert cancelled["value"] is True
    assert failed_calls
    assert "cancelled" in failed_calls[0]["error_message"].lower()
    assert result["status"] == "failed"


def test_finalize_stale_job_when_running_is_orphaned(monkeypatch) -> None:
    from app.api import routes

    failed_calls: list[dict] = []

    class FakeRepository:
        async def mark_job_failed(self, **kwargs) -> None:  # noqa: ANN003
            failed_calls.append(kwargs)

        async def get_job(self, job_id: str) -> dict:  # noqa: ARG002
            return {"status": "failed", "id": "job-2"}

    monkeypatch.setattr(routes, "_repository", FakeRepository())
    monkeypatch.setattr(routes._processor, "tasks", {})  # noqa: SLF001

    old_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    job = {
        "status": "running",
        "updated_at": old_time,
        "pipeline": {"analysis": None},
    }
    result = asyncio.run(routes._finalize_stale_job_if_needed("job-2", job))  # noqa: SLF001

    assert failed_calls
    assert "no pipeline stage updates" in failed_calls[0]["error_message"].lower()
    assert result["status"] == "failed"


def test_finalize_stale_job_handles_naive_updated_at(monkeypatch) -> None:
    from app.api import routes

    failed_calls: list[dict] = []

    class FakeRepository:
        async def mark_job_failed(self, **kwargs) -> None:  # noqa: ANN003
            failed_calls.append(kwargs)

        async def get_job(self, job_id: str) -> dict:  # noqa: ARG002
            return {"status": "failed", "id": "job-4"}

    monkeypatch.setattr(routes, "_repository", FakeRepository())
    monkeypatch.setattr(routes._processor, "tasks", {})  # noqa: SLF001

    old_naive = (datetime.now(timezone.utc) - timedelta(minutes=10)).replace(tzinfo=None).isoformat()
    job = {
        "status": "running",
        "updated_at": old_naive,
        "pipeline": {"analysis": None},
    }
    result = asyncio.run(routes._finalize_stale_job_if_needed("job-4", job))  # noqa: SLF001

    assert failed_calls
    assert result["status"] == "failed"


def test_finalize_stale_job_fails_running_job_without_stage_updates(monkeypatch) -> None:
    from app.api import routes

    failed_calls: list[dict] = []
    cancelled = {"value": False}

    class FakeRepository:
        async def mark_job_failed(self, **kwargs) -> None:  # noqa: ANN003
            failed_calls.append(kwargs)

        async def get_job(self, job_id: str) -> dict:  # noqa: ARG002
            return {"status": "failed", "id": "job-5"}

    class FakeTask:
        def done(self) -> bool:
            return False

        def cancel(self) -> None:
            cancelled["value"] = True

    monkeypatch.setattr(routes, "_repository", FakeRepository())
    monkeypatch.setattr(routes._processor, "tasks", {"job-5": FakeTask()})  # noqa: SLF001

    old_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    job = {
        "status": "running",
        "updated_at": old_time,
        "stages": [],
        "pipeline": {"analysis": None},
    }
    result = asyncio.run(routes._finalize_stale_job_if_needed("job-5", job))  # noqa: SLF001

    assert cancelled["value"] is True
    assert failed_calls
    assert "no pipeline stage updates" in failed_calls[0]["error_message"].lower()
    assert result["status"] == "failed"
