from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from pypdf import PdfReader
try:
    import pypdfium2 as pdfium
    import pytesseract
except Exception:  # pragma: no cover - optional runtime dependency guard.
    pdfium = None
    pytesseract = None

from app.agents.base_agent import BaseAgent
from app.models.pipeline_models import CollectorOutput, RawPage, UploadedDocumentInput
from app.repositories.pipeline_repository import PipelineRepository


class CollectorAgent(BaseAgent):
    """Ingest PDF and persist raw per-page extraction output."""

    def __init__(self, name: str, repository: PipelineRepository) -> None:
        super().__init__(name)
        self.repository = repository

    async def run(self, input_data: UploadedDocumentInput) -> CollectorOutput:
        file_path = Path(input_data.file_path)
        file_bytes = file_path.read_bytes()
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        metadata = input_data.metadata or {}
        document_id = str(metadata.get("job_id") or uuid4())
        raw_pages = self._extract_pages(file_bytes)

        collector_output = CollectorOutput(
            document_id=document_id,
            file_path=str(file_path),
            filename=input_data.filename,
            sha256=sha256,
            page_count=len(raw_pages),
            raw_pages=raw_pages,
            ingestion_timestamp=datetime.now(timezone.utc),
        )
        await self.repository.save_raw_document(collector_output.model_dump(mode="json"))
        await self.repository.save_raw_pages(
            document_id,
            [page.model_dump(mode="json") for page in raw_pages],
        )
        return collector_output

    def _extract_pages(self, file_bytes: bytes) -> List[RawPage]:
        """Extract page text with OCR fallback for weak pages."""
        native_texts = self._extract_native_texts(file_bytes)
        pages: List[RawPage] = []
        for index, native_text in enumerate(native_texts, start=1):
            ocr_text: Optional[str] = None
            if self._needs_fallback(native_text):
                ocr_text = self._extract_ocr_text(file_bytes, page_number=index)

            text, extraction_method, needs_fallback = self._select_best_text(native_text, ocr_text)
            pages.append(
                RawPage(
                    page_number=index,
                    raw_text=text,
                    extraction_method=extraction_method,
                    needs_fallback=needs_fallback,
                )
            )
        return pages

    def _extract_native_texts(self, file_bytes: bytes) -> List[str]:
        reader = PdfReader(io.BytesIO(file_bytes))
        return [(page.extract_text() or "").strip() for page in reader.pages]

    def _extract_ocr_text(self, file_bytes: bytes, page_number: int) -> Optional[str]:
        """Run OCR on a specific page (1-indexed)."""
        if not pdfium or not pytesseract:
            return None
        try:
            pdf = pdfium.PdfDocument(io.BytesIO(file_bytes))
            page = pdf[page_number - 1]
            bitmap = page.render(scale=2.5)
            image = bitmap.to_pil()
            text = pytesseract.image_to_string(image, lang="fra+eng", config="--psm 6").strip()
            page.close()
            pdf.close()
            return text or None
        except Exception:
            return None

    def _select_best_text(self, native_text: str, ocr_text: Optional[str]) -> Tuple[str, str, bool]:
        native = native_text.strip()
        ocr = (ocr_text or "").strip()

        if ocr and (not native or len(ocr) > len(native)):
            selected = ocr
            method = "ocr"
        elif native and ocr:
            selected = f"{native}\n\n[OCR supplement]\n{ocr}"
            method = "pypdf+ocr"
        else:
            selected = native
            method = "pypdf"

        return selected, method, self._needs_fallback(selected)

    def _needs_fallback(self, text: str) -> bool:
        if not text:
            return True
        return len(text) < 80 or text.count(" ") < 12
