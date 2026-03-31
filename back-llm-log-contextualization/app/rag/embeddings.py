from __future__ import annotations

import math
import re
from typing import List


class EmbeddingsBackend:
    """Deterministic hashing-based embeddings for lightweight RAG retrieval."""

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    async def embed_documents(self, documents: List[str]) -> List[List[float]]:
        return [self._embed(doc) for doc in documents]

    async def embed_query(self, query: str) -> List[float]:
        return self._embed(query)

    def _embed(self, text: str) -> List[float]:
        vector = [0.0] * self.dimension
        for token in re.findall(r"[a-zA-ZÀ-ÿ0-9]{3,}", text.lower()):
            idx = hash(token) % self.dimension
            vector[idx] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0:
            vector = [value / norm for value in vector]
        return vector
