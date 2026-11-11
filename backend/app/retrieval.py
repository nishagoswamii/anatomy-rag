"""Retrieval over the textbook chunks.

Modes, each exposed separately so evals can compare them:
- vector:        dense embeddings only
- bm25:          keyword search only
- hybrid:        vector + BM25 fused with reciprocal rank fusion
- hybrid_rerank: hybrid candidates reordered by a cross-encoder
- vector_gated:  vector ranking; the cross-encoder only scores the final
                 passages, to decide whether the question is in scope
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import lancedb
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from lancedb.query import MatchQuery

from app.config import Settings
from app.index import TABLE, embed_text

Mode = Literal["vector", "bm25", "hybrid", "hybrid_rerank", "vector_gated"]
RRF_K = 60
# BGE's recommended instruction for short-query -> passage retrieval.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@dataclass
class Retrieved:
    chunk: dict
    score: float  # cross-encoder logit when reranked, else a fused/raw score


@dataclass
class RetrievalResult:
    passages: list[Retrieved]
    top_score: float | None  # best rerank score; None if not reranked

    def in_scope(self, threshold: float) -> bool:
        return bool(self.passages) and (self.top_score is None or self.top_score >= threshold)


class Retriever:
    def __init__(self, settings: Settings):
        self.settings = settings
        cache = str(settings.model_cache_dir)
        self.embedder = TextEmbedding(settings.embed_model, cache_dir=cache)
        self.reranker = TextCrossEncoder(settings.rerank_model, cache_dir=cache)
        self.table = lancedb.connect(str(settings.index_dir)).open_table(TABLE)
        rows = self.table.to_arrow().select(["id", "chunk"]).to_pylist()
        self.chunks: dict[str, dict] = {r["id"]: json.loads(r["chunk"]) for r in rows}

    # --- individual stages -------------------------------------------------

    def vector_search(self, query: str, k: int) -> list[str]:
        vec = next(iter(self.embedder.embed([QUERY_INSTRUCTION + query])))
        rows = self.table.search(vec.tolist()).select(["id", "_distance"]).limit(k).to_list()
        return [r["id"] for r in rows]

    def bm25_search(self, query: str, k: int) -> list[str]:
        q = MatchQuery(query, "search_text")
        try:
            rows = (
                self.table.search(q, query_type="fts").select(["id", "_score"]).limit(k).to_list()
            )
        except ValueError:
            return []  # e.g. a query made only of stop words
        return [r["id"] for r in rows]

    @staticmethod
    def rrf(*rankings: list[str], k: int = RRF_K) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, cid in enumerate(ranking):
                scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
        return sorted(scores.items(), key=lambda x: -x[1])

    def rerank(self, query: str, ids: list[str]) -> list[tuple[str, float]]:
        docs = [embed_text(self.chunks[i]) for i in ids]
        scores = list(self.reranker.rerank(query, docs))
        return sorted(zip(ids, scores, strict=True), key=lambda x: -x[1])

    # --- full pipeline -----------------------------------------------------

    def retrieve(
        self, query: str, mode: Mode | None = None, k: int | None = None
    ) -> RetrievalResult:
        mode = mode or self.settings.retrieval_mode
        k = k or self.settings.k_final
        n = self.settings.k_candidates
        if mode == "vector_gated":
            ids = self.vector_search(query, k)
            scores = dict(self.rerank(query, ids)) if ids else {}
            return RetrievalResult(
                [Retrieved(self.chunks[i], float(scores[i])) for i in ids],
                float(max(scores.values())) if scores else None,
            )
        if mode == "vector":
            ranked = [(i, 0.0) for i in self.vector_search(query, k)]
        elif mode == "bm25":
            ranked = [(i, 0.0) for i in self.bm25_search(query, k)]
        else:
            fused = self.rrf(self.vector_search(query, n), self.bm25_search(query, n))
            if mode == "hybrid":
                ranked = fused[:k]
            else:
                reranked = self.rerank(query, [i for i, _ in fused[:n]])[:k]
                return RetrievalResult(
                    [Retrieved(self.chunks[i], float(s)) for i, s in reranked],
                    float(reranked[0][1]) if reranked else None,
                )
        return RetrievalResult([Retrieved(self.chunks[i], s) for i, s in ranked], None)
