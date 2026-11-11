"""Build the LanceDB index (vectors + BM25 full-text) from data/chunks.jsonl.

    uv run python -m app.index

Runs at Docker build time, so the deployed image ships a ready index and the
model weights, and needs no downloads on start-up.
"""

from __future__ import annotations

import json
import time

import lancedb
import pyarrow as pa
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from app.config import Settings, get_settings

TABLE = "chunks"


def embed_text(chunk: dict) -> str:
    """What gets embedded: the chunk plus its location in the book."""
    where = f"{chunk['section']} {chunk['section_title']}"
    if chunk.get("heading"):
        where += f" - {chunk['heading']}"
    return f"{where}\n{' '.join(chunk['blocks'])}"


def search_text(chunk: dict) -> str:
    """What BM25 indexes: same as above, so section titles count as keywords."""
    return embed_text(chunk)


def load_chunks(settings: Settings) -> list[dict]:
    with settings.chunks_path.open() as f:
        return [json.loads(line) for line in f]


def build(settings: Settings) -> None:
    t0 = time.time()
    chunks = load_chunks(settings)
    settings.model_cache_dir.mkdir(parents=True, exist_ok=True)
    embedder = TextEmbedding(settings.embed_model, cache_dir=str(settings.model_cache_dir))
    # Download the reranker now too, so it's baked into the image.
    TextCrossEncoder(settings.rerank_model, cache_dir=str(settings.model_cache_dir))

    vectors = list(embedder.embed([embed_text(c) for c in chunks], batch_size=64))
    dim = len(vectors[0])
    table = pa.table(
        {
            "id": [c["id"] for c in chunks],
            "search_text": [search_text(c) for c in chunks],
            "chunk": [json.dumps(c, ensure_ascii=False) for c in chunks],
            "vector": pa.array([v.tolist() for v in vectors], type=pa.list_(pa.float32(), dim)),
        }
    )
    db = lancedb.connect(str(settings.index_dir))
    tbl = db.create_table(TABLE, data=table, mode="overwrite")
    tbl.create_fts_index("search_text", replace=True, stem=True, remove_stop_words=True)
    print(
        f"indexed {len(chunks)} chunks (dim {dim}) in {time.time() - t0:.0f}s -> {settings.index_dir}"
    )


if __name__ == "__main__":
    build(get_settings())
