"""
FastAPI REST API Routes — the HTTP layer of the BI SQL Assistant.

This module owns *only* HTTP concerns: validating input, orchestrating the
domain services, mapping failures onto status codes and shaping the response.
It never talks to an LLM provider directly — that is the job of
``app.llm.service`` — and it never returns anything the response models in
``app.api.schemas`` do not explicitly declare.

Endpoints:
  POST /api/query       — NL question → SQL + data + chart + insight
  GET  /api/schema      — Current schema metadata
  GET  /api/history     — Recent query history for a session
  GET  /api/suggestions — Schema-aware NL query suggestions
  GET  /api/dashboard   — Pre-built analytics panels
  GET  /api/health      — Health check (schema + LLM provider)
  GET  /api/metrics     — Performance dashboard data
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.analytics.dashboard import build_dashboard
from app.api.schemas import (
    DashboardResponse,
    HealthResponse,
    HistoryResponse,
    MetricsResponse,
    QueryRequest,
    QueryResponse,
    SchemaResponse,
    SuggestionsResponse,
)
from app.api.serialization import safe_records, sanitize_chart_json
from app.conversation.memory import conversation_memory
from app.insights.generator import generate_insight
from app.llm.base import LLMError
from app.llm.confidence import build_schema_lookup, score_sql_confidence
from app.llm.prompts import format_fk_relationships
from app.llm.service import FALLBACK_SUGGESTIONS, llm_service
from app.llm.templates import find_similar_templates, initialize_templates
from app.monitoring.metrics import metrics_tracker
from app.schema.embeddings import embed_schema, retrieve_relevant_tables
from app.schema.extractor import extract_schema_metadata, get_schema_for_prompt
from app.sql.executor import execute_query
from app.sql.retry import retry_failed_query
from app.sql.validator import validate_sql
from app.visualization.engine import determine_chart_type, render_chart

router = APIRouter(prefix="/api", tags=["BI Assistant"])

# ── Cached schema metadata (loaded at startup) ───────────────
_schema_cache: list[dict] = []
_schema_tables: dict = {}
_fk_map: dict = {}


def api_error(
    status_code: int,
    error: str,
    message: str,
    **extra: Any,
) -> HTTPException:
    """Build an HTTPException carrying the standard error envelope."""
    detail: dict[str, Any] = {"error": error, "message": message}
    detail.update({k: v for k, v in extra.items() if v is not None})
    return HTTPException(status_code=status_code, detail=detail)


# ── Schema Initialization ────────────────────────────────────

def initialize_schema() -> None:
    """Load and embed schema metadata. Called at app startup."""
    global _schema_cache, _schema_tables, _fk_map

    logger.info("🔄 Initializing schema metadata...")
    _schema_cache = extract_schema_metadata()
    _schema_tables, _fk_map = build_schema_lookup(_schema_cache)
    embed_schema(_schema_cache)
    initialize_templates()
    logger.info(f"✅ Schema initialized: {len(_schema_cache)} tables")


def _render_presentation(df, question: str) -> tuple[str, dict | None]:
    """Chart selection + rendering (CPU-bound; runs in a worker thread)."""
    chart_type = determine_chart_type(df)
    figure = render_chart(df, chart_type, title=question)

    chart_json: dict | None = None
    if figure is not None:
        raw = figure if isinstance(figure, dict) else figure.to_plotly_json()
        chart_json = sanitize_chart_json(raw)

    return chart_type.value, chart_json


# ── Main Query Endpoint ──────────────────────────────────────

@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Answer a natural-language business question",
)
async def process_query(request: QueryRequest) -> QueryResponse:
    """
    Main pipeline: NL question → SQL → execute → visualise → insight.

    Every blocking step (embedding lookup, SQL execution, chart rendering) is
    dispatched to a worker thread and every LLM call is awaited, so the event
    loop stays free to serve other requests while a query is in flight.
    """
    question = request.question
    session_id = request.session_id or str(uuid.uuid4())
    warnings: list[str] = []

    logger.info(f"📥 Query: '{question}' (session: {session_id[:8]}...)")

    if not _schema_cache:
        raise api_error(
            503,
            "schema_unavailable",
            "The database schema has not been loaded yet. Please try again shortly.",
        )

    try:
        # 1. Retrieve the most relevant tables (embedding similarity).
        relevant_tables = await asyncio.to_thread(
            retrieve_relevant_tables,
            query=question,
            top_k=4,
            all_tables_metadata=_schema_cache,
        )
        if not relevant_tables:
            relevant_tables = _schema_cache

        # 2. Build the schema context for the prompt.
        schema_context = get_schema_for_prompt(relevant_tables)
        fk_relationships = format_fk_relationships(relevant_tables)

        # 3. Few-shot examples + multi-turn context.
        templates = await asyncio.to_thread(find_similar_templates, question, top_k=2)
        conv_context = conversation_memory.get_context(session_id)

        # 4. Generate SQL through the LLM service layer.
        generation = await llm_service.generate_sql(
            schema_context=schema_context,
            fk_relationships=fk_relationships,
            question=question,
            conversation_context=conv_context,
            similar_templates=templates,
        )

        # 5. Validate before anything touches the database.
        known_table_names = set(_schema_tables.keys())
        validation = validate_sql(generation.sql, known_table_names)
        warnings.extend(validation.warnings)

        if not validation.is_valid:
            raise api_error(
                422,
                "sql_validation_failed",
                "The generated query did not pass the safety checks. "
                "Try rephrasing your question.",
                details=validation.errors,
            )

        sql = validation.sql

        # 6. Confidence score.
        confidence = score_sql_confidence(sql, _schema_tables, _fk_map)

        # 7. Execute (blocking driver → worker thread).
        exec_result = await asyncio.to_thread(execute_query, sql)
        retry_count = 0

        # 8. Self-correct on failure.
        if not exec_result.success and exec_result.error:
            retry_result = await retry_failed_query(
                original_sql=sql,
                original_error=exec_result.error,
                question=question,
                schema_context=schema_context,
                known_tables=known_table_names,
            )
            retry_count = retry_result.total_retries

            if retry_result.succeeded and retry_result.final_result:
                exec_result = retry_result.final_result
                sql = retry_result.final_sql
                warnings.append(f"Query succeeded after {retry_count} retry(s)")
                confidence = score_sql_confidence(sql, _schema_tables, _fk_map)
            else:
                metrics_tracker.record(
                    question=question,
                    sql=sql,
                    success=False,
                    execution_time_ms=exec_result.execution_time_ms,
                    confidence_score=confidence.score,
                    retry_count=retry_count,
                    error=exec_result.error,
                )
                raise api_error(
                    422,
                    "query_execution_failed",
                    "The query could not be executed successfully, even after "
                    "automatic correction. Try rephrasing your question.",
                    details=exec_result.error,
                    sql=sql,
                    retry_count=retry_count,
                )

        # 9. Presentation layer: chart + insight (CPU-bound → worker thread).
        df = exec_result.data
        chart_type, chart_json = await asyncio.to_thread(
            _render_presentation, df, question
        )
        insight = await asyncio.to_thread(generate_insight, question, exec_result)

        # 10. Record the turn and the metrics.
        conversation_memory.add_turn(
            session_id=session_id,
            question=question,
            sql=sql,
            result_columns=exec_result.columns,
            result_row_count=exec_result.row_count,
        )
        metrics_tracker.record(
            question=question,
            sql=sql,
            success=True,
            execution_time_ms=exec_result.execution_time_ms,
            confidence_score=confidence.score,
            row_count=exec_result.row_count,
            retry_count=retry_count,
        )

        # 11. Build the response. Only declared fields are serialised.
        return QueryResponse(
            question=question,
            sql=sql,
            data=safe_records(df),
            columns=exec_result.columns,
            row_count=exec_result.row_count,
            chart_type=chart_type,
            chart_json=chart_json,
            insight=insight,
            confidence={
                "score": confidence.score,
                "level": confidence.level,
                "checks": confidence.checks,
                "warnings": confidence.warnings,
            },
            execution_time_ms=exec_result.execution_time_ms,
            retry_count=retry_count,
            warnings=warnings,
            session_id=session_id,
            generation={
                "provider": llm_service.provider_name,
                "model": generation.meta.model,
                "latency_ms": generation.meta.latency_ms,
                "completion_tokens": generation.meta.completion_tokens,
                "reasoning_suppressed": generation.meta.reasoning_suppressed,
            },
        )

    except HTTPException:
        raise
    except LLMError as exc:
        logger.error(f"LLM failure: {type(exc).__name__}: {exc}")
        raise api_error(exc.http_status, exc.code, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - final safety net
        logger.exception(f"Pipeline error: {exc}")
        raise api_error(
            500,
            "internal_error",
            "Something went wrong while answering that question.",
        ) from exc


# ── Schema Endpoint ──────────────────────────────────────────

@router.get("/schema", response_model=SchemaResponse, summary="Database schema")
async def get_schema() -> SchemaResponse:
    """Return the cached schema metadata used to ground SQL generation."""
    return SchemaResponse(
        tables=[
            {
                "name": table["table_name"],
                "columns": [c["name"] for c in table["columns"]],
                "row_count": table["row_count"],
                "foreign_keys": table["foreign_keys"],
            }
            for table in _schema_cache
        ]
    )


# ── History Endpoint ─────────────────────────────────────────

@router.get("/history", response_model=HistoryResponse, summary="Session history")
async def get_history(
    session_id: str = Query(..., min_length=1, max_length=64)
) -> HistoryResponse:
    """Return the stored turns for one conversation session."""
    return HistoryResponse(
        session_id=session_id,
        history=conversation_memory.get_history(session_id),
    )


# ── Suggestions Endpoint ─────────────────────────────────────

@router.get(
    "/suggestions",
    response_model=SuggestionsResponse,
    summary="Suggested business questions",
)
async def get_suggestions() -> SuggestionsResponse:
    """
    Ask the model for analytical questions that suit the current schema.

    Suggestions are a convenience, not core functionality, so a provider failure
    degrades to a curated fallback list instead of failing the request.
    """
    if not _schema_cache:
        return SuggestionsResponse(suggestions=list(FALLBACK_SUGGESTIONS), source="fallback")

    try:
        schema_context = get_schema_for_prompt(_schema_cache)
        suggestions = await llm_service.generate_suggestions(schema_context)
        return SuggestionsResponse(suggestions=suggestions, source="model")
    except Exception as exc:  # noqa: BLE001 - degrade, never fail
        logger.warning(f"Suggestion generation failed, using fallback: {exc}")
        return SuggestionsResponse(
            suggestions=list(FALLBACK_SUGGESTIONS), source="fallback"
        )


# ── Dashboard Endpoint ───────────────────────────────────────

@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    summary="Pre-built analytics panels",
)
async def get_dashboard() -> DashboardResponse:
    """
    Return the fixed analytics panels used by the dashboard view.

    No LLM is involved and the browser never sees a connection string: the
    queries are server-owned constants executed on the read-only connection.
    """
    try:
        payload = await asyncio.to_thread(build_dashboard)
        return DashboardResponse(**payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"Dashboard build failed: {exc}")
        raise api_error(
            503,
            "dashboard_unavailable",
            "Dashboard data could not be loaded from the database.",
        ) from exc


# ── Health Check ─────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, summary="Service health")
async def health_check() -> HealthResponse:
    """Report schema readiness and LLM provider connectivity."""
    provider_health = await llm_service.health()
    schema_ok = len(_schema_cache) > 0

    return HealthResponse(
        status="healthy" if (provider_health.available and schema_ok) else "degraded",
        llm="connected" if provider_health.available else "disconnected",
        provider=provider_health.provider,
        model=provider_health.model,
        detail=provider_health.detail,
        schema_status=(
            f"{len(_schema_cache)} tables loaded" if schema_ok else "not loaded"
        ),
    )


# ── Metrics Endpoint ─────────────────────────────────────────

@router.get("/metrics", response_model=MetricsResponse, summary="Performance metrics")
async def get_metrics() -> MetricsResponse:
    """Return aggregate performance metrics and the most recent queries."""
    return MetricsResponse(
        stats=metrics_tracker.get_aggregate_stats(),
        recent=metrics_tracker.get_recent_queries(10),
    )
