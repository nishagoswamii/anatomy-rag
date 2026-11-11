"""Test doubles for the Claude client and the retriever."""

from __future__ import annotations

from types import SimpleNamespace as NS

from app.retrieval import RetrievalResult, Retrieved


def make_chunk(cid: str = "22.2-00", blocks: list[str] | None = None) -> dict:
    return {
        "id": cid,
        "chapter": 22,
        "chapter_title": "The Respiratory System",
        "section": cid.split("-")[0],
        "section_title": "The Lungs",
        "heading": "Gross Anatomy of the Lungs",
        "page_start": 985,
        "page_end": 986,
        "url": "https://openstax.org/books/anatomy-and-physiology-2e/pages/22-2-the-lungs",
        "blocks": blocks or ["The right lung has three lobes.", "The left lung has two lobes."],
    }


class FakeRetriever:
    def __init__(self, score: float = 3.0):
        self.score = score
        self.chunks = {"22.2-00": make_chunk()}
        self.queries: list[str] = []

    def retrieve(self, query, mode=None, k=None):
        self.queries.append(query)
        return RetrievalResult([Retrieved(make_chunk(), self.score)], self.score)


def text_delta(index, text):
    return NS(type="content_block_delta", index=index, delta=NS(type="text_delta", text=text))


def citation_delta(index, source_index=0, start=0, end=1, cited="The right lung has three lobes."):
    citation = NS(
        type="search_result_location",
        search_result_index=source_index,
        start_block_index=start,
        end_block_index=end,
        cited_text=cited,
    )
    return NS(
        type="content_block_delta", index=index, delta=NS(type="citations_delta", citation=citation)
    )


def final_message(stop_reason="end_turn", cited=True, model="claude-opus-5-5"):
    block = NS(
        type="text", text="The right lung has three lobes.", citations=[object()] if cited else None
    )
    usage = NS(input_tokens=4000, output_tokens=500, iterations=None)
    return NS(stop_reason=stop_reason, content=[block], usage=usage, model=model)


class FakeStream:
    def __init__(self, events, message):
        self.events = events
        self.message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def gen():
            for e in self.events:
                yield e

        return gen()

    async def get_final_message(self):
        return self.message


class FakeClient:
    """Mimics the parts of anthropic.AsyncAnthropic used by Generator."""

    def __init__(self, events=None, message=None, rewrite_text="standalone query"):
        self.stream_calls: list[dict] = []
        self.create_calls: list[dict] = []
        events = (
            events if events is not None else [text_delta(1, "The right lung "), citation_delta(1)]
        )
        message = message or final_message()

        def stream(**kwargs):
            self.stream_calls.append(kwargs)
            return FakeStream(events, message)

        async def create(**kwargs):
            self.create_calls.append(kwargs)
            usage = NS(input_tokens=200, output_tokens=20, iterations=None)
            return NS(
                stop_reason="end_turn",
                content=[NS(type="text", text=rewrite_text)],
                usage=usage,
                model=kwargs["model"],
            )

        self.beta = NS(messages=NS(stream=stream))
        self.messages = NS(create=create)
