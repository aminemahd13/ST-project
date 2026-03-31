from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List


class VectorStore:
    """Lightweight persistent vector store based on a JSON index."""

    def __init__(self, index_path: Path) -> None:
        self.index_path = index_path
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self._loaded = False
        self._vectors: List[List[float]] = []
        self._metadatas: List[dict] = []

    async def add(self, vectors: Any, metadatas: List[dict] | None = None) -> None:
        await self._ensure_loaded()
        metadata_list = metadatas or [{} for _ in vectors]
        for vector, metadata in zip(vectors, metadata_list):
            self._vectors.append([float(value) for value in vector])
            self._metadatas.append(dict(metadata))
        await self._persist()

    async def similarity_search(self, query_vector: Any, k: int = 5) -> List[dict]:
        await self._ensure_loaded()
        if not self._vectors:
            return []

        query = [float(v) for v in query_vector]
        scored = []
        for idx, vector in enumerate(self._vectors):
            score = sum(a * b for a, b in zip(query, vector))
            item = dict(self._metadatas[idx])
            item["score"] = round(score, 5)
            scored.append(item)
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:k]

    async def count(self) -> int:
        await self._ensure_loaded()
        return len(self._vectors)

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self.index_path.exists():
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
            self._vectors = raw.get("vectors", [])
            self._metadatas = raw.get("metadatas", [])
        self._loaded = True

    async def _persist(self) -> None:
        payload = {
            "vectors": self._vectors,
            "metadatas": self._metadatas,
        }
        self.index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
