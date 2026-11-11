import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.generation import Generator
from app.main import create_app
from tests.fakes import FakeClient, FakeRetriever


def make_client(**settings_overrides) -> TestClient:
    settings = Settings(**settings_overrides)
    generator = Generator(settings, FakeRetriever(), FakeClient())
    return TestClient(create_app(settings, generator))


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def test_chat_streams_events():
    with make_client() as client:
        r = client.post("/api/chat", json={"question": "How many lobes does the right lung have?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert [e["type"] for e in parse_sse(r.text)] == ["sources", "text", "citation", "done"]


def test_health():
    with make_client() as client:
        assert client.get("/api/health").json() == {
            "status": "ok",
            "chunks": 1,
            "llm_configured": True,
        }


def test_rejects_bad_history():
    with make_client() as client:
        r = client.post(
            "/api/chat",
            json={"question": "q", "history": [{"role": "assistant", "text": "hi"}]},
        )
    assert r.status_code == 422


def test_rejects_long_question():
    with make_client(max_question_chars=10) as client:
        r = client.post("/api/chat", json={"question": "x" * 11})
    assert r.status_code == 413


def test_rate_limit():
    with make_client(per_ip_per_minute=2) as client:
        codes = [client.post("/api/chat", json={"question": "q"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_daily_budget():
    with make_client(daily_budget_usd=0.01) as client:
        r = client.post("/api/chat", json={"question": "q"})
    assert r.status_code == 503
    assert r.json()["error"] == "budget_exhausted"
