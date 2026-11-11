Retrieval eval: 45 answerable questions, embeddings `BAAI/bge-small-en-v1.5`, reranker `jinaai/jina-reranker-v1-turbo-en`.

| Mode | Hit@1 | Hit@3 | Hit@6 | MRR | Hit@1 broad | Hit@1 exact-term | p50 latency |
|---|---|---|---|---|---|---|---|
| vector | 91% | 100% | 100% | 0.96 | 90% | 93% | 8 ms |
| bm25 | 64% | 98% | 100% | 0.80 | 63% | 67% | 1 ms |
| hybrid | 87% | 100% | 100% | 0.93 | 90% | 80% | 9 ms |
| hybrid_rerank | 87% | 100% | 100% | 0.93 | 87% | 87% | 2895 ms |

Relevance gate: lowest answerable score -0.72, highest out-of-scope score -1.43.

| Threshold | Answerable passed | Out-of-scope blocked |
|---|---|---|
| -6.0 | 100% | 0% |
| -4.0 | 100% | 20% |
| -2.0 | 100% | 70% |
| -1.0 | 100% | 100% |
| +0.0 | 69% | 100% |
| +1.0 | 9% | 100% |
| +2.0 | 0% | 100% |
