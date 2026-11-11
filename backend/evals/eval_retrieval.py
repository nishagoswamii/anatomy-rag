"""Retrieval evaluation. Free to run (no API calls), so it also runs in CI.

    uv run python -m evals.eval_retrieval [--rerank-model NAME] [--out results/retrieval.md]

A retrieved chunk counts as relevant when its section is one of the question's
expected sections. Reports hit@k and MRR per retrieval mode, and how well the
relevance gate separates answerable from out-of-scope questions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from app.config import get_settings
from app.retrieval import Retriever

EVAL_DIR = Path(__file__).parent
MODES = ("vector", "bm25", "hybrid", "hybrid_rerank", "vector_gated")
K = 6


def load_gold() -> list[dict]:
    with (EVAL_DIR / "gold.jsonl").open() as f:
        return [json.loads(line) for line in f]


def first_hit_rank(sections: list[str], expected: list[str]) -> int | None:
    for rank, s in enumerate(sections, 1):
        if s in expected:
            return rank
    return None


def evaluate(retriever: Retriever, gold: list[dict], gate_mode: str = "vector_gated") -> dict:
    answerable = [g for g in gold if g["kind"] == "answerable"]
    others = [g for g in gold if g["kind"] != "answerable"]
    report: dict = {"modes": {}, "gate": {}, "misses": []}

    for mode in MODES:
        ranks, times, subsets = [], [], []
        for g in answerable:
            t0 = time.perf_counter()
            res = retriever.retrieve(g["question"], mode, k=K)
            times.append(time.perf_counter() - t0)
            rank = first_hit_rank(
                [p.chunk["section"] for p in res.passages], g["expected_sections"]
            )
            ranks.append(rank)
            subsets.append(g.get("difficulty", "broad"))
            if mode == "hybrid_rerank" and rank is None:
                report["misses"].append(
                    {"id": g["id"], "got": [p.chunk["id"] for p in res.passages[:3]]}
                )
        n = len(ranks)
        report["modes"][mode] = {
            "hit@1": sum(1 for r in ranks if r == 1) / n,
            "hit@3": sum(1 for r in ranks if r and r <= 3) / n,
            f"hit@{K}": sum(1 for r in ranks if r) / n,
            "mrr": sum(1 / r for r in ranks if r) / n,
            "p50_ms": statistics.median(times) * 1000,
        }
        for subset in sorted(set(subsets)):
            sub = [r for r, d in zip(ranks, subsets, strict=True) if d == subset]
            report["modes"][mode][f"hit@1:{subset}"] = sum(1 for r in sub if r == 1) / len(sub)
            report["modes"][mode][f"mrr:{subset}"] = sum(1 / r for r in sub if r) / len(sub)

    # Relevance gate: top rerank score for every question.
    scores = {
        g["id"]: retriever.retrieve(g["question"], gate_mode, k=K).top_score
        for g in answerable + others
    }
    ans_scores = [scores[g["id"]] for g in answerable]
    oos_scores = [scores[g["id"]] for g in others if g["kind"] == "out_of_scope"]
    sweep = []
    for t in (-6.0, -4.0, -2.0, -1.0, 0.0, 1.0, 2.0):
        sweep.append(
            {
                "threshold": t,
                "answerable_passed": sum(s >= t for s in ans_scores) / len(ans_scores),
                "out_of_scope_blocked": sum(s < t for s in oos_scores) / len(oos_scores),
            }
        )
    report["gate_mode"] = gate_mode
    report["gate"] = {
        "answerable_min": min(ans_scores),
        "out_of_scope_max": max(oos_scores),
        "sweep": sweep,
        "adversarial_scores": {
            g["id"]: round(scores[g["id"]], 2) for g in others if g["kind"] == "adversarial"
        },
    }
    return report


def to_markdown(report: dict, settings) -> str:
    lines = [
        f"Retrieval eval: {sum(1 for _ in load_gold() if _['kind'] == 'answerable')} answerable questions, "
        f"embeddings `{settings.embed_model}`, reranker `{settings.rerank_model}`.",
        "",
        f"| Mode | Hit@1 | Hit@3 | Hit@{K} | MRR | Hit@1 broad | Hit@1 exact-term | p50 latency |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode, m in report["modes"].items():
        lines.append(
            f"| {mode} | {m['hit@1']:.0%} | {m['hit@3']:.0%} | {m[f'hit@{K}']:.0%} | "
            f"{m['mrr']:.2f} | {m.get('hit@1:broad', 0):.0%} | {m.get('hit@1:exact_term', 0):.0%} | "
            f"{m['p50_ms']:.0f} ms |"
        )
    g = report["gate"]
    lines += [
        "",
        f"Relevance gate (`{report['gate_mode']}`): lowest answerable score {g['answerable_min']:.2f}, "
        f"highest out-of-scope score {g['out_of_scope_max']:.2f}.",
        "",
        "| Threshold | Answerable passed | Out-of-scope blocked |",
        "|---|---|---|",
    ]
    for row in g["sweep"]:
        lines.append(
            f"| {row['threshold']:+.1f} | {row['answerable_passed']:.0%} | {row['out_of_scope_blocked']:.0%} |"
        )
    if report["misses"]:
        lines += ["", "Misses (hybrid_rerank): " + ", ".join(m["id"] for m in report["misses"])]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank-model")
    parser.add_argument(
        "--gate-mode", default="vector_gated", choices=["hybrid_rerank", "vector_gated"]
    )
    parser.add_argument("--out", type=Path, default=EVAL_DIR / "results" / "retrieval.md")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the default pipeline regresses (used in CI)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if args.rerank_model:
        settings = settings.model_copy(update={"rerank_model": args.rerank_model})
    report = evaluate(Retriever(settings), load_gold(), args.gate_mode)
    md = to_markdown(report, settings)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2))
    print(md)
    print("misses:", json.dumps(report["misses"], indent=1))
    print("adversarial scores:", report["gate"]["adversarial_scores"])

    if args.check:
        failures = check(report, settings)
        for f in failures:
            print("FAIL:", f)
        raise SystemExit(1 if failures else 0)


def check(report: dict, settings) -> list[str]:
    failures = []
    hit3 = report["modes"][settings.retrieval_mode]["hit@3"]
    if hit3 < 0.95:
        failures.append(f"{settings.retrieval_mode} hit@3 {hit3:.0%} < 95%")
    g = report["gate"]
    if g["answerable_min"] < settings.relevance_threshold:
        failures.append(
            f"an answerable question scores {g['answerable_min']:.2f}, below the gate threshold "
            f"{settings.relevance_threshold}"
        )
    if g["out_of_scope_max"] >= settings.relevance_threshold:
        failures.append(
            f"an out-of-scope question scores {g['out_of_scope_max']:.2f}, above the gate threshold"
        )
    return failures


if __name__ == "__main__":
    main()
