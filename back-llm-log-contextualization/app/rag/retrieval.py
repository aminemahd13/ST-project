from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List

from pypdf import PdfReader

from app.config.settings import settings
from app.rag.embeddings import EmbeddingsBackend
from app.rag.vector_store import VectorStore


class Retriever:
    """Retrieve context chunks from seeded historical notice PDFs."""

    def __init__(
        self,
        vector_store: VectorStore | None = None,
        embeddings: EmbeddingsBackend | None = None,
        seed_dir: Path | None = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.vector_store = vector_store or VectorStore(settings.storage_path / "rag_index.json")
        self.embeddings = embeddings or EmbeddingsBackend()
        self.seed_dir = (seed_dir or settings.rag_seed_path).resolve()
        self._seeded = False
        self._seed_lock = asyncio.Lock()

    async def retrieve(self, query: str, top_k: int = 5) -> List[dict]:
        await self._seed_if_needed()
        query_vector = await self.embeddings.embed_query(query)
        hits = await self.vector_store.similarity_search(query_vector, k=top_k)
        return hits

    async def _seed_if_needed(self) -> None:
        if self._seeded:
            return
        async with self._seed_lock:
            if self._seeded:
                return
            if await self.vector_store.count() > 0:
                self._seeded = True
                return
            if not self.seed_dir.exists():
                self.logger.warning("RAG seed directory not found", extra={"seed_dir": str(self.seed_dir)})
                self._seeded = True
                return

            chunks: List[str] = []
            metadatas: List[dict] = []
            for pdf_path in sorted(self.seed_dir.glob("*.pdf")):
                for page_number, page_text in enumerate(self._read_pdf_pages(pdf_path), start=1):
                    for chunk_index, chunk in enumerate(self._chunk_text(page_text)):
                        chunks.append(chunk)
                        metadatas.append(
                            {
                                "source": pdf_path.name,
                                "page": page_number,
                                "chunk_index": chunk_index,
                                "text": chunk,
                            }
                        )

            if chunks:
                vectors = await self.embeddings.embed_documents(chunks)
                await self.vector_store.add(vectors=vectors, metadatas=metadatas)
                self.logger.info("RAG index seeded", extra={"chunk_count": len(chunks)})
            self._seeded = True

    def _read_pdf_pages(self, path: Path) -> List[str]:
        try:
            reader = PdfReader(str(path))
        except Exception:  # noqa: BLE001
            return []
        pages: List[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        return pages

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
        if len(text) <= chunk_size:
            return [text]
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            chunks.append(text[start:end])
            if end == len(text):
                break
            start = max(end - overlap, start + 1)
        return chunks
