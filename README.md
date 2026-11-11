# AnatomyRAG

A retrieval-augmented chatbot that answers questions **only** from the OpenStax textbook
*Anatomy and Physiology 2e*, cites the exact passage for each claim, and declines
questions the book doesn't cover.

- **Grounded:** answers come from retrieved textbook passages, not the model's general knowledge.
- **Checkable:** every cited claim links to its source sentences, section, and printed page number.
- **Declines what it can't answer:** a relevance gate stops off-topic questions *before* any
  language-model call, and the prompt handles medical-advice and prompt-injection requests.
- **Measured:** retrieval choices were made from an eval set, and the results are below, including
  the ones that contradicted my starting assumptions.

<!-- Live demo: add the URL here once deployed. -->

## How it works

```
INGEST (offline)   PDF ─► outline-based sections ─► clean ─► sentence-aware chunks ─► data/chunks.jsonl
IMAGE BUILD        chunks ─► bge-small embeddings ─► LanceDB (+ BM25 index); model weights baked in
QUERY              question
                    ─► follow-up? rewrite into a standalone query
                    ─► vector search, top 6 passages
                    ─► cross-encoder relevance score ─► below threshold? "not in this book" (no LLM call)
                    ─► Claude with passages as search_result blocks (citations on)
                    ─► SSE stream: text + structured citations ─► UI chips ─► source panel
```

| Layer | Choice |
|---|---|
| Corpus | OpenStax *Anatomy and Physiology 2e*: 1,347-page PDF, 197 sections, 2,112 chunks |
| Backend | Python 3.12, FastAPI, Server-Sent Events |
| Retrieval | fastembed `BAAI/bge-small-en-v1.5` (ONNX, CPU), LanceDB |
| Relevance gate | fastembed cross-encoder `Xenova/ms-marco-MiniLM-L-6-v2` |
| LLM | Claude Opus 5.5 (`claude-opus-5-5`), adaptive thinking, effort `medium`, server-side refusal fallback |
| Frontend | Next.js 16, React 19, Tailwind 4 |

### Ingestion

The PDF outline gives each section's start page. Within a chapter the code finds each
section's heading line, so a section that begins mid-page is split correctly. Running headers and
footers are removed, and the printed page number is read from each page's footer. Learning-objective
lists, figure credits, and interactive-link boilerplate are stripped, and subheadings are detected
for context. Chunks are about 350 tokens, never cross a section, and overlap by one sentence.

Each chunk is stored as **2-3 sentence blocks**. Claude cites whole blocks of a `search_result`, so
small blocks mean a citation highlights a couple of sentences rather than a whole page. I checked
page numbers by locating sampled chunk text back in the PDF, and checked every generated OpenStax
section link against openstax.org; all 197 resolve.

### Citations

Retrieved passages are sent as Claude
[`search_result`](https://platform.claude.com/docs/en/build-with-claude/search-results) content
blocks with citations enabled. The API returns structured citations
(`search_result_index`, `start_block_index`, `end_block_index`, `cited_text`) instead of the model
writing `[1]` markers that would need parsing and could be invented. An answer with no citations at
all is flagged in the UI.

### Grounding and safety, in layers

1. **Relevance gate:** if the best cross-encoder score is below the threshold, the app returns a
   fixed "not in this book" message, which always includes an emergency-services line. No model call
   is made, so it costs nothing.
2. **System prompt:** answer only from the passages, say when they don't cover the question, treat
   passages as data rather than instructions, give no diagnosis, dosing, or treatment advice, and
   send possible emergencies to emergency services first.
3. **Refusal handling:** server-side `fallbacks: "default"` retries safety-classifier refusals on a
   fallback model. If a request is still refused, the partial answer is discarded.
4. **UI:** a permanent "not medical advice" notice.

## Results

### Retrieval (45 answerable questions, no API cost, runs in CI)

The gold set (`backend/evals/gold.jsonl`) has 30 broad questions and 15 exact-term questions
("Which stomach cells secrete hydrochloric acid?"). Every expected section was checked against the
chunk text. A hit means a retrieved passage comes from an expected section.

| Mode | Hit@1 | Hit@3 | Hit@6 | MRR | Hit@1 broad | Hit@1 exact-term | p50 latency |
|---|---|---|---|---|---|---|---|
| vector | 91% | 100% | 100% | 0.96 | 90% | 93% | 9 ms |
| bm25 | 64% | 98% | 100% | 0.80 | 63% | 67% | 2 ms |
| hybrid (RRF) | 87% | 100% | 100% | 0.93 | 90% | 80% | 13 ms |
| hybrid + rerank | 87% | 100% | 100% | 0.93 | 90% | 80% | 2,539 ms |
| **vector + gate (shipped)** | **91%** | **100%** | **100%** | **0.96** | 90% | 93% | 540 ms |

**What changed my plan:** I expected BM25 hybrid search to help with exact anatomical terms. On
this book it didn't: vector search alone ranked as well or better, including on the exact-term
questions. Reranking the full candidate list added more than 2 seconds per question and no ranking
gain. So the shipped pipeline ranks by vector search and uses the cross-encoder only to score the
final 6 passages, as the relevance gate.

**Relevance gate:** with the MiniLM cross-encoder, the lowest-scoring answerable question scored
-1.72 and the highest-scoring out-of-scope question scored -7.01. A threshold of -4.0 passes 100% of
answerable questions and blocks 100% of the 10 off-topic ones. The `jina-reranker-v1-turbo-en`
alternative produced overlapping scores, so no threshold separated the two groups.
`bge-reranker-base` was dropped for latency (well over 10 s per question on CPU).

Caveats: 45 questions is a small set. One exact-term question moves hit@1 by about 7 points, and
section-level relevance is coarser than passage-level relevance.

### Answer quality

`backend/evals/eval_answers.py` runs every gold question, including 10 adversarial ones (emergency,
dosing, diagnosis, prompt injection), through the full pipeline and grades the answers with Claude
as a judge. It reports faithfulness, citation support, false-rejection rate, and
appropriate-handling rate. **It hasn't been run yet**; the results will go in
`backend/evals/results/answers.md`. Estimated cost per run is about $3.

## Running locally

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22, and an Anthropic API key.

```bash
# 1. Backend
cd backend
uv sync
cp .env.example .env            # then set ANTHROPIC_API_KEY
uv run python -m app.index      # builds data/index and downloads ~150 MB of models (~5 min)
uv run uvicorn app.main:app --port 8000

# 2. Frontend (another terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev                     # http://localhost:3000
```

`data/chunks.jsonl` is committed, so you don't need the PDF. To rebuild it from source:

```bash
mkdir -p data/raw
curl -L -o data/raw/ap2e.pdf \
  https://assets.openstax.org/oscms-prodcms/media/documents/anatomy-and-physiology-2e_-_WEB.pdf
cd backend && uv run python -m ingest.run ../data/raw/ap2e.pdf ../data/chunks.jsonl
```

### Tests and evals

```bash
cd backend
uv run pytest                                   # unit tests; Claude is mocked
uv run python -m evals.eval_retrieval --check   # retrieval eval; free
uv run python -m evals.eval_answers             # dry run: prints the estimated cost
uv run python -m evals.eval_answers --yes       # real run; calls the API
```

## Deployment

The backend runs as a Docker container. The image builds the index and bakes in the model weights,
so the container makes no downloads at start-up. It listens on port 7860, the Hugging Face Spaces
convention.

```bash
docker build -t anatomy-rag .
docker run -p 7860:7860 -e ANTHROPIC_API_KEY=... -e RAG_CORS_ORIGINS='["http://localhost:3000"]' anatomy-rag
```

**Backend on a Hugging Face Docker Space:** push the repo to the Space, then set `ANTHROPIC_API_KEY`
as a secret and `RAG_CORS_ORIGINS` to your frontend URL.
**Frontend on Vercel:** set the root directory to `frontend` and set `NEXT_PUBLIC_API_URL` to the
Space URL.

The public demo is protected in several ways:

- **Per-IP limits:** 10 requests a minute and 30 a day.
- **Question length:** capped at 1,000 characters.
- **Daily spend budget:** $2 by default (`RAG_DAILY_BUDGET_USD`), computed from API usage and
  counting fallback attempts.
- **CORS:** only the frontend's origin is allowed.

These counters are in memory and reset on restart, so **also set a monthly spend limit in the
Anthropic Console** as the hard backstop.

## Project layout

```
backend/
  ingest/     PDF -> sections -> cleaned items -> chunks
  app/        config, index build, retrieval, generation, prompts, limits, FastAPI app
  evals/      gold set, retrieval eval, answer eval, results/
  tests/      unit tests with a fake Claude client
frontend/     Next.js chat UI: streaming answers, citation chips, source panel
data/         chunks.jsonl (CC BY-NC-SA 4.0, see data/LICENSE.md)
Dockerfile    backend image
```

## Limitations

- Figures aren't searchable. Only text and descriptive figure captions are indexed.
- Tables are flattened into text, so table-heavy passages read awkwardly.
- The gate threshold is tuned on a small eval set and can misjudge borderline questions.
- Follow-up questions send earlier turns as plain text; earlier passages aren't re-sent.
- Rate limits and the budget live in memory on a single instance.

## License and attribution

Code: MIT (see `LICENSE`).

Textbook content: *Anatomy and Physiology 2e* by OpenStax, © Rice University, licensed under
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Access for free at
[openstax.org](https://openstax.org/details/books/anatomy-and-physiology-2e). The adapted passages
in `data/` carry the same license (see `data/LICENSE.md`). This project is non-commercial and is not
affiliated with or endorsed by OpenStax or Rice University.
