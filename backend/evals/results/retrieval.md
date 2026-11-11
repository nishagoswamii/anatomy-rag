Retrieval eval: 45 answerable questions, embeddings `BAAI/bge-small-en-v1.5`, reranker `Xenova/ms-marco-MiniLM-L-6-v2`.

| Mode | Hit@1 | Hit@3 | Hit@6 | MRR | Hit@1 broad | Hit@1 exact-term | p50 latency |
|---|---|---|---|---|---|---|---|
| vector | 91% | 100% | 100% | 0.96 | 90% | 93% | 9 ms |
| bm25 | 64% | 98% | 100% | 0.80 | 63% | 67% | 2 ms |
| hybrid | 87% | 100% | 100% | 0.93 | 90% | 80% | 13 ms |
| hybrid_rerank | 87% | 100% | 100% | 0.93 | 90% | 80% | 2539 ms |
| vector_gated | 91% | 100% | 100% | 0.96 | 90% | 93% | 540 ms |

Relevance gate (`vector_gated`): lowest answerable score -1.72, highest out-of-scope score -7.01.

| Threshold | Answerable passed | Out-of-scope blocked |
|---|---|---|
| -6.0 | 100% | 100% |
| -4.0 | 100% | 100% |
| -2.0 | 100% | 100% |
| -1.0 | 98% | 100% |
| +0.0 | 91% | 100% |
| +1.0 | 87% | 100% |
| +2.0 | 82% | 100% |
