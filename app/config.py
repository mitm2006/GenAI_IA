"""Application configuration loaded from environment variables.

Secrets (notably ``GROQ_API_KEY``) are *only* ever read from the environment or
from a local ``.env`` file that is excluded from version control. Nothing in
this module hard-codes a credential, and no credential is ever forwarded to the
browser — the React client talks exclusively to this FastAPI backend.
"""

from pydantic_settings import BaseSettings
from pydantic import Field, field_validator


class Settings(BaseSettings):
    """Central configuration for the BI SQL Assistant."""

    # ── Database ──────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./bi_analytics.db",
        description="Primary database connection string (read-write, for seeding)",
    )
    db_readonly_url: str = Field(
        default="sqlite:///./bi_analytics.db",
        description="Read-only connection string used for query execution",
    )

    # ── LLM provider (Groq) ──────────────────────────────────
    llm_provider: str = Field(
        default="groq",
        description="Identifier of the LLM provider implementation to load",
    )
    groq_api_key: str = Field(
        default="",
        description="Groq API key — MUST be supplied via the GROQ_API_KEY env var",
    )
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL of the Groq OpenAI-compatible REST API",
    )
    llm_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Groq-hosted model used for SQL generation",
    )
    llm_temperature: float = Field(
        default=0.1,
        description="Default sampling temperature (low = deterministic SQL)",
    )
    llm_timeout_seconds: float = Field(
        default=60.0,
        description="Per-request timeout for Groq chat completions",
    )
    llm_max_attempts: int = Field(
        default=3,
        description="Transport-level attempts per LLM call (retries 429/5xx)",
    )
    llm_reasoning_effort: str = Field(
        default="low",
        description="Reasoning budget for reasoning-capable models: low|medium|high",
    )
    llm_reasoning_format: str = Field(
        default="hidden",
        description=(
            "Groq reasoning delivery mode. 'hidden' asks the API to omit "
            "reasoning entirely; anything else is still stripped server-side."
        ),
    )
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformer model for schema embeddings",
    )

    # ── App ───────────────────────────────────────────────────
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True
    cors_allow_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Comma-separated list of allowed browser origins",
    )

    # ── Query Safety ──────────────────────────────────────────
    max_query_limit: int = Field(
        default=1000,
        description="Maximum LIMIT value allowed in generated SQL",
    )
    query_timeout_seconds: int = Field(
        default=10,
        description="PostgreSQL statement_timeout in seconds",
    )
    max_retry_attempts: int = Field(
        default=3,
        description="Number of LLM retries on SQL execution failure",
    )

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @field_validator("llm_reasoning_effort")
    @classmethod
    def _valid_effort(cls, v: str) -> str:
        allowed = {"low", "medium", "high"}
        value = (v or "low").strip().lower()
        return value if value in allowed else "low"

    @property
    def cors_origins(self) -> list[str]:
        """Parse the comma-separated CORS origin list."""
        origins = [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]
        return origins or ["http://localhost:5173"]

    @property
    def llm_configured(self) -> bool:
        """True when a provider credential is present."""
        return bool(self.groq_api_key.strip())


# Singleton instance — import this everywhere
settings = Settings()
