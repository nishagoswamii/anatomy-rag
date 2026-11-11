from types import SimpleNamespace as NS

import pytest

from app.config import Settings
from app.generation import Generator, Turn, build_messages, usage_cost
from app.prompts import OUT_OF_SCOPE_MESSAGE
from tests.fakes import FakeClient, FakeRetriever, final_message, text_delta


async def collect(gen):
    return [e async for e in gen]


def make(score=3.0, **client_kwargs):
    client = FakeClient(**client_kwargs)
    retriever = FakeRetriever(score)
    return Generator(Settings(), retriever, client), client, retriever


def test_build_messages_puts_search_results_before_question():
    retriever = FakeRetriever()
    result = retriever.retrieve("q")
    history = [Turn("user", "What are lungs?"), Turn("assistant", "Organs for breathing.")]
    messages = build_messages(history, "How many lobes?", result)

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "What are lungs?"  # history is plain text
    content = messages[-1]["content"]
    assert content[0]["type"] == "search_result"
    assert content[0]["citations"] == {"enabled": True}
    assert [b["text"] for b in content[0]["content"]] == result.passages[0].chunk["blocks"]
    assert content[0]["title"].startswith("22.2 The Lungs: Gross Anatomy of the Lungs (p. 985-986)")
    assert content[-1] == {"type": "text", "text": "How many lobes?"}


def test_usage_cost_counts_every_fallback_attempt():
    iterations = [
        NS(model="claude-opus-5-5", input_tokens=1_000_000, output_tokens=0),
        NS(model="claude-opus-5", input_tokens=0, output_tokens=1_000_000),
    ]
    message = NS(
        model="claude-opus-5",
        usage=NS(input_tokens=0, output_tokens=1_000_000, iterations=iterations),
    )
    cost, tokens = usage_cost(message)
    assert cost == pytest.approx(4.0 + 25.0)
    assert tokens == {"input": 1_000_000, "output": 1_000_000}


async def test_answer_streams_sources_text_citations_and_done():
    gen, client, _ = make()
    events = await collect(gen.answer("How many lobes does the right lung have?", []))
    types = [e["type"] for e in events]

    assert types == ["sources", "text", "citation", "done"]
    assert events[2]["source_index"] == 0 and events[2]["end_block"] == 1
    done = events[-1]
    assert done["stop_reason"] == "end_turn" and done["uncited"] is False
    assert done["cost_usd"] == pytest.approx(4000 / 1e6 * 4 + 500 / 1e6 * 20)

    call = client.stream_calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "medium"}
    assert "temperature" not in call
    assert client.create_calls == []  # no rewrite without history


async def test_out_of_scope_question_makes_no_api_call():
    gen, client, _ = make(score=-9.0)
    events = await collect(gen.answer("How do I bake bread?", []))
    assert [e["type"] for e in events] == ["out_of_scope", "done"]
    assert events[0]["message"] == OUT_OF_SCOPE_MESSAGE
    assert client.stream_calls == [] and client.create_calls == []


async def test_refusal_resets_partial_answer():
    gen, _, _ = make(
        events=[text_delta(1, "Partial")], message=final_message(stop_reason="refusal")
    )
    events = await collect(gen.answer("question", []))
    assert [e["type"] for e in events] == ["sources", "text", "reset", "error", "done"]
    assert events[3]["code"] == "refusal"


async def test_uncited_answer_is_flagged():
    gen, _, _ = make(message=final_message(cited=False))
    events = await collect(gen.answer("question", []))
    assert events[-1]["uncited"] is True


async def test_follow_up_is_rewritten_before_retrieval():
    gen, client, retriever = make(rewrite_text="How many lobes does the left lung have?")
    history = [
        Turn("user", "How many lobes does the right lung have?"),
        Turn("assistant", "Three."),
    ]
    events = await collect(gen.answer("And the left one?", history))
    assert retriever.queries == ["How many lobes does the left lung have?"]
    assert client.create_calls[0]["output_config"] == {"effort": "low"}
    # The model still sees the user's own wording.
    assert client.stream_calls[0]["messages"][-1]["content"][-1]["text"] == "And the left one?"
    assert events[-1]["query"] == "How many lobes does the left lung have?"
