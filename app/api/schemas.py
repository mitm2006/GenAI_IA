"""
API contract — request and response models.

These models are the security boundary of the HTTP layer in both directions:

* **Inbound**, they reject malformed or oversized input before any prompt is
  built or any SQL is generated.
* **Outbound**, they act as an allow-list. FastAPI serialises exactly the fields
  declared here, so an object that accidentally carried extra data (model
  reasoning, provider internals, credentials) still could not reach the browser.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ── Requests ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    """A natural-language analytics question."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Business question in plain English",
        examples=["Top 10 products by revenue"],
    )
    session_id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Opaque session identifier used for multi-turn context",
    )

    @field_validator("question")
    @classmethod
    def _clean_question(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 3:
            raise ValueError("Question is too short.")
        return cleaned

    @field_validator("session_id")
    @classmethod
    def _clean_session(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not all(ch.isalnum() or ch in "-_" for ch in cleaned):
            raise ValueError("session_id may only contain letters, digits, '-' and '_'.")
        return cleaned


# ── Shared response fragments ─────────────────────────────────

class ConfidenceCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class Confidence(BaseModel):
    score: int = Field(ge=0, le=100)
    level: Literal["high", "medium", "low"]
    checks: list[ConfidenceCheck] = []
    warnings: list[str] = []


class GenerationInfo(BaseModel):
    """Non-sensitive telemetry about the LLM call behind a response.

    Deliberately carries no model output other than what is already in
    ``sql``/``insight``: no reasoning, no raw provider payload.
    """

    provider: str
    model: str
    latency_ms: float
    completion_tokens: int
    reasoning_suppressed: bool = True


# ── Responses ─────────────────────────────────────────────────

class QueryResponse(BaseModel):
    """Result of the full NL → SQL → data → chart → insight pipeline."""

    question: str
    sql: str
    data: list[dict[str, Any]]
    columns: list[str]
    row_count: int
    chart_type: str
    chart_json: Optional[dict[str, Any]] = None
    insight: str
    confidence: Confidence
    execution_time_ms: float
    retry_count: int = 0
    warnings: list[str] = []
    session_id: str
    generation: Optional[GenerationInfo] = None


class SchemaTable(BaseModel):
    name: str
    columns: list[str]
    row_count: int
    foreign_keys: list[dict[str, Any]] = []


class SchemaResponse(BaseModel):
    tables: list[SchemaTable]


class HistoryTurn(BaseModel):
    question: str
    sql: str
    result_columns: list[str]
    result_row_count: int
    timestamp: str


class HistoryResponse(BaseModel):
    session_id: str
    history: list[HistoryTurn]


class SuggestionsResponse(BaseModel):
    suggestions: list[str]
    source: Literal["model", "fallback"] = "model"


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded"]
    llm: Literal["connected", "disconnected"]
    provider: str
    model: str
    detail: str = ""
    schema_status: str
    reasoning_suppression: Literal["enabled"] = "enabled"


class MetricsResponse(BaseModel):
    stats: dict[str, Any]
    recent: list[dict[str, Any]]


class DashboardKpis(BaseModel):
    total_revenue: float
    total_profit: float
    total_orders: int
    unique_customers: int
    avg_order_value: float


class DashboardResponse(BaseModel):
    kpis: DashboardKpis
    panels: dict[str, list[dict[str, Any]]]
    generated_in_ms: float


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for every non-2xx API response."""

    error: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable explanation for the UI")
    details: Optional[Any] = None
    sql: Optional[str] = None
    retry_count: Optional[int] = None
