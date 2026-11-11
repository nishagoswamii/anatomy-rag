from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    # Every setting is read from RAG_<NAME> (e.g. RAG_EFFORT=high), from the
    # environment or backend/.env.
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=BACKEND_DIR / ".env", extra="ignore"
    )

    # Claude. The key is read here (not only by the SDK) so it can live in backend/.env.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "RAG_ANTHROPIC_API_KEY")
    )
    model: str = "claude-opus-5-5"
    rewrite_model: str = "claude-opus-5-5"
    effort: str = "medium"
    rewrite_effort: str = "low"
    max_tokens: int = 8000
    history_turns: int = 6

    # Data and models
    chunks_path: Path = REPO_DIR / "data" / "chunks.jsonl"
    index_dir: Path = REPO_DIR / "data" / "index"
    model_cache_dir: Path = REPO_DIR / "data" / "models"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    # Retrieval (defaults chosen from evals/results/retrieval.md)
    retrieval_mode: str = "vector_gated"
    k_candidates: int = 30
    k_final: int = 6
    # Cross-encoder logit below which a question is treated as out of scope.
    relevance_threshold: float = -4.0

    # Public demo protection
    cors_origins: list[str] = ["http://localhost:3000"]
    per_ip_per_minute: int = 10
    per_ip_per_day: int = 30
    max_question_chars: int = 1000
    daily_budget_usd: float = 2.0
    trust_proxy_headers: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
