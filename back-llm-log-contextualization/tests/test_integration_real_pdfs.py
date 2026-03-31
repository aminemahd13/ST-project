import asyncio
import os
from pathlib import Path

import pytest

from app.models.pipeline_models import UploadedDocumentInput
from app.orchestrator.orchestrator import Orchestrator


@pytest.mark.integration
def test_pipeline_smoke_with_real_pdf() -> None:
    if os.getenv("RUN_REAL_PDF_TESTS", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("Enable RUN_REAL_PDF_TESTS=1 to execute real PDF integration tests.")

    logs_dir = Path(__file__).resolve().parents[2] / "context_file" / "logs_document"
    pdf_files = sorted(logs_dir.glob("*.pdf"))
    if not pdf_files:
        pytest.skip("No real PDF logs available.")

    sample_pdf = pdf_files[0]
    orchestrator = Orchestrator()
    payload = UploadedDocumentInput(
        file_path=str(sample_pdf),
        filename=sample_pdf.name,
        metadata={"job_id": "integration-smoke"},
    )
    result = asyncio.run(orchestrator.process_document(payload))
    assert result.document_id is not None
    assert result.collector is not None
