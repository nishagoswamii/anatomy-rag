"""FastAPI app: POST /api/chat streams an answer as Server-Sent Events.

uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Literal

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from app.config import Settings, get_settings
from app.generation import Generator, Turn
from app.limits import ESTIMATED_COST_USD, DailyBudget, RateLimiter
from app.retrieval import Retriever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("anatomy_rag")

BOOK = {
    "title": "Anatomy and Physiology 2e",
    "publisher": "OpenStax",
    "url": "https://openstax.org/details/books/anatomy-and-physiology-2e",
    "license": "CC BY-NC-SA 4.0",
    "attribution": "Access for free at openstax.org.",
}


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    question: str
    history: list[HistoryTurn] = []

    @field_validator("question")
    @classmethod
    def strip_question(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("question is empty")
        return v

    @field_validator("history")
    @classmethod
    def alternating(cls, v: list[HistoryTurn]) -> list[HistoryTurn]:
        for i, turn in enumerate(v):
            expected = "user" if i % 2 == 0 else "assistant"
            if turn.role != expected:
                raise ValueError("history must alternate user/assistant, starting with user")
        if v and v[-1].role != "assistant":
            raise ValueError("history must end with an assistant turn")
        return v


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # The last entry was added by our proxy; earlier ones can be spoofed.
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def create_app(settings: Settings | None = None, generator: Generator | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if generator is None:
            retriever = Retriever(settings)
            key = settings.anthropic_api_key
            # With no key here, the SDK falls back to its own credential lookup.
            client = (
                anthropic.AsyncAnthropic(api_key=key.get_secret_value())
                if key
                else anthropic.AsyncAnthropic()
            )
            app.state.generator = Generator(settings, retriever, client)
            app.state.chunk_count = len(retriever.chunks)
            app.state.llm_configured = bool(
                key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            )
            if not app.state.llm_configured:
                log.warning(
                    "No ANTHROPIC_API_KEY found; out-of-scope questions work but answers will fail"
                )
        else:
            app.state.generator = generator
            app.state.chunk_count = len(generator.retriever.chunks)
            app.state.llm_configured = True
        yield

    app = FastAPI(title="AnatomyRAG", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    app.state.rate_limiter = RateLimiter(settings.per_ip_per_minute, settings.per_ip_per_day)
    app.state.budget = DailyBudget(settings.daily_budget_usd)

    @app.get("/api/health")
    async def health(request: Request):
        return {
            "status": "ok",
            "chunks": request.app.state.chunk_count,
            "llm_configured": request.app.state.llm_configured,
        }

    @app.get("/api/meta")
    async def meta():
        return {
            "book": BOOK,
            "model": settings.model,
            "retrieval_mode": settings.retrieval_mode,
            "embed_model": settings.embed_model,
            "rerank_model": settings.rerank_model,
            "max_question_chars": settings.max_question_chars,
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequest, request: Request):
        if len(body.question) > settings.max_question_chars:
            return JSONResponse(
                {
                    "error": "question_too_long",
                    "message": f"Please keep questions under {settings.max_question_chars} characters.",
                },
                status_code=413,
            )
        hit = request.app.state.rate_limiter.check(client_ip(request, settings))
        if hit:
            period = "minute" if hit == "minute" else "day"
            return JSONResponse(
                {
                    "error": "rate_limited",
                    "message": f"You've reached the demo limit for this {period}. Please try again later.",
                },
                status_code=429,
            )
        budget: DailyBudget = request.app.state.budget
        if not budget.reserve(ESTIMATED_COST_USD):
            return JSONResponse(
                {
                    "error": "budget_exhausted",
                    "message": "The demo has reached its daily usage limit. Please come back tomorrow.",
                },
                status_code=503,
            )

        gen: Generator = request.app.state.generator
        history = [Turn(t.role, t.text) for t in body.history]

        async def events():
            settled = False
            try:
                async for event in gen.answer(body.question, history):
                    if event["type"] == "done":
                        budget.settle(ESTIMATED_COST_USD, event.get("cost_usd", 0.0))
                        settled = True
                        log.info(
                            "answered stop=%s cost=$%.4f top=%s",
                            event.get("stop_reason"),
                            event.get("cost_usd", 0.0),
                            event.get("top_score"),
                        )
                    yield {"event": event["type"], "data": json.dumps(event)}
            except Exception:
                log.exception("chat stream failed")
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {
                            "type": "error",
                            "code": "internal",
                            "message": "Something went wrong. Please try again.",
                        }
                    ),
                }
            finally:
                if not settled:
                    log.info("stream ended without done event; reservation kept")

        return EventSourceResponse(events(), ping=15)

    return app


app = create_app()
