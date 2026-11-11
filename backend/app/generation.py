"""Answer generation with Claude, grounded in retrieved passages.

Passages are sent as `search_result` blocks with citations enabled, so the API
returns structured citations (search_result_index + block range) rather than
the model writing "[1]"-style markers into its text.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import anthropic

from app.config import Settings
from app.prompts import OUT_OF_SCOPE_MESSAGE, REFUSAL_MESSAGE, REWRITE_PROMPT, SYSTEM_PROMPT
from app.retrieval import RetrievalResult, Retriever

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
# USD per million tokens (input, output). Fallback targets are listed so the
# daily budget stays accurate when a request is served by another model.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
DEFAULT_PRICE = (5.0, 25.0)


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str


Event = dict[str, Any]


def passage_title(chunk: dict) -> str:
    title = f"{chunk['section']} {chunk['section_title']}"
    if chunk.get("heading"):
        title += f": {chunk['heading']}"
    pages = chunk["page_start"]
    if chunk["page_end"] != chunk["page_start"]:
        pages = f"{chunk['page_start']}-{chunk['page_end']}"
    return f"{title} (p. {pages})"


def search_result_blocks(result: RetrievalResult) -> list[dict]:
    return [
        {
            "type": "search_result",
            "source": p.chunk["url"],
            "title": passage_title(p.chunk),
            "content": [{"type": "text", "text": b} for b in p.chunk["blocks"]],
            "citations": {"enabled": True},
        }
        for p in result.passages
    ]


def build_messages(history: list[Turn], question: str, result: RetrievalResult) -> list[dict]:
    # History is plain text only: no search results, citations, or thinking
    # blocks from earlier turns, so nothing earlier in the request is edited
    # between turns and citation indices always refer to the current passages.
    messages: list[dict] = [{"role": t.role, "content": t.text} for t in history]
    messages.append(
        {
            "role": "user",
            "content": [*search_result_blocks(result), {"type": "text", "text": question}],
        }
    )
    return messages


def sources_payload(result: RetrievalResult) -> list[dict]:
    return [
        {
            "index": i,
            "id": p.chunk["id"],
            "chapter": p.chunk["chapter"],
            "chapter_title": p.chunk["chapter_title"],
            "section": p.chunk["section"],
            "section_title": p.chunk["section_title"],
            "heading": p.chunk.get("heading"),
            "page_start": p.chunk["page_start"],
            "page_end": p.chunk["page_end"],
            "url": p.chunk["url"],
            "blocks": p.chunk["blocks"],
            "score": round(p.score, 3),
        }
        for i, p in enumerate(result.passages)
    ]


def usage_cost(message: Any) -> tuple[float, dict]:
    """Cost of a final message in USD, counting every attempt (fallbacks included)."""
    usage = message.usage
    iterations = getattr(usage, "iterations", None) or []
    attempts = []
    for it in iterations:
        attempts.append(
            (
                getattr(it, "model", None) or message.model,
                it.input_tokens or 0,
                it.output_tokens or 0,
            )
        )
    if not attempts:
        attempts = [(message.model, usage.input_tokens or 0, usage.output_tokens or 0)]
    cost = 0.0
    for model, inp, out in attempts:
        pin, pout = PRICES.get(model, DEFAULT_PRICE)
        cost += inp / 1e6 * pin + out / 1e6 * pout
    tokens = {"input": sum(a[1] for a in attempts), "output": sum(a[2] for a in attempts)}
    return cost, tokens


class Generator:
    def __init__(self, settings: Settings, retriever: Retriever, client: anthropic.AsyncAnthropic):
        self.settings = settings
        self.retriever = retriever
        self.client = client

    async def rewrite_query(self, history: list[Turn], question: str) -> tuple[str, float]:
        """Make a follow-up question standalone for retrieval. Falls back to the raw question."""
        if not history:
            return question, 0.0
        transcript = "\n".join(f"{t.role}: {t.text[:1500]}" for t in history[-4:])
        try:
            msg = await self.client.messages.create(
                model=self.settings.rewrite_model,
                max_tokens=2000,
                system=REWRITE_PROMPT,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.rewrite_effort},
                messages=[
                    {
                        "role": "user",
                        "content": f"Conversation so far:\n{transcript}\n\nFollow-up question: {question}",
                    }
                ],
            )
        except anthropic.APIError as e:
            log.warning("query rewrite failed: %s", e)
            return question, 0.0
        cost, _ = usage_cost(msg)
        if msg.stop_reason != "end_turn":
            return question, cost
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        return (text.splitlines()[0].strip() if text else question), cost

    async def answer(self, question: str, history: list[Turn]) -> AsyncIterator[Event]:
        """Stream an answer as UI events. The last event is always `done` or `error`."""
        history = history[-2 * self.settings.history_turns :]
        query, rewrite_cost = await self.rewrite_query(history, question)
        result = self.retriever.retrieve(query)

        if not result.in_scope(self.settings.relevance_threshold):
            yield {"type": "out_of_scope", "message": OUT_OF_SCOPE_MESSAGE}
            yield {
                "type": "done",
                "stop_reason": "out_of_scope",
                "cost_usd": rewrite_cost,
                "query": query,
                "top_score": result.top_score,
            }
            return

        yield {"type": "sources", "sources": sources_payload(result), "query": query}

        try:
            async with self.client.beta.messages.stream(
                model=self.settings.model,
                max_tokens=self.settings.max_tokens,
                system=SYSTEM_PROMPT,
                messages=build_messages(history, question, result),
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.effort},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                async for event in stream:
                    if (
                        event.type == "content_block_start"
                        and event.content_block.type == "fallback"
                    ):
                        # A fallback model continues from the partial answer; nothing to discard.
                        log.info("served by fallback model after refusal")
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            yield {"type": "text", "block": event.index, "text": delta.text}
                        elif delta.type == "citations_delta":
                            c = delta.citation
                            if c.type == "search_result_location":
                                yield {
                                    "type": "citation",
                                    "block": event.index,
                                    "source_index": c.search_result_index,
                                    "start_block": c.start_block_index,
                                    "end_block": c.end_block_index,
                                    "cited_text": c.cited_text,
                                }
                message = await stream.get_final_message()
        except anthropic.RateLimitError:
            yield {
                "type": "error",
                "code": "rate_limited",
                "message": "The service is busy. Please try again in a minute.",
            }
            return
        except anthropic.APIStatusError as e:
            log.error("Claude API error %s: %s", e.status_code, e.message)
            code = "overloaded" if e.status_code >= 500 else "api_error"
            yield {
                "type": "error",
                "code": code,
                "message": "Something went wrong generating the answer. Please try again.",
            }
            return
        except anthropic.APIConnectionError as e:
            log.error("Claude API connection error: %s", e)
            yield {
                "type": "error",
                "code": "connection",
                "message": "Couldn't reach the language model. Please try again.",
            }
            return

        cost, tokens = usage_cost(message)
        if message.stop_reason == "refusal":
            # Still declined after any fallback: drop the partial answer.
            yield {"type": "reset"}
            yield {"type": "error", "code": "refusal", "message": REFUSAL_MESSAGE}
            yield {
                "type": "done",
                "stop_reason": "refusal",
                "cost_usd": cost + rewrite_cost,
                "tokens": tokens,
            }
            return

        cited = any(getattr(b, "citations", None) for b in message.content if b.type == "text")
        yield {
            "type": "done",
            "stop_reason": message.stop_reason,
            "truncated": message.stop_reason == "max_tokens",
            "uncited": not cited,
            "model": message.model,
            "cost_usd": cost + rewrite_cost,
            "tokens": tokens,
            "query": query,
            "top_score": result.top_score,
        }
