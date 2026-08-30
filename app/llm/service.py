"""
LLM service layer — the only place that knows both *prompts* and *providers*.

    React UI → FastAPI routes → LLMService → LLMProvider → Groq → gpt-oss-20b

Routes deal in HTTP concerns; providers deal in transport concerns. This layer
sits between them and owns the application-level LLM tasks: turn a question into
SQL, repair a failed query, propose analytical questions. Everything it returns
has already been reasoning-sanitized by the provider, and it applies one further
sanitation pass so that a future provider that forgets to do so still cannot leak
deliberation into an API response.
"""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.llm.base import LLMResponse, ProviderHealth
from app.llm.client import get_llm_provider
from app.llm.prompts import (
    build_retry_prompt,
    build_sql_prompt,
    build_suggestion_prompt,
)
from app.llm.sanitizer import strip_reasoning

# Used when the model is unreachable or returns nothing parseable.
FALLBACK_SUGGESTIONS: list[str] = [
    "What were total sales in 2024?",
    "Top 10 products by revenue",
    "Monthly profit trend for 2024",
    "Sales by customer segment",
    "Top 5 cities by profit",
    "Average discount by product category",
    "Which shipping mode generates the most revenue?",
    "Customer loyalty tier distribution",
]


@dataclass(frozen=True)
class GenerationMeta:
    """Non-sensitive telemetry about a single LLM call."""

    model: str
    latency_ms: float
    completion_tokens: int
    reasoning_suppressed: bool

    @classmethod
    def from_response(cls, response: LLMResponse) -> "GenerationMeta":
        return cls(
            model=response.model,
            latency_ms=response.latency_ms,
            completion_tokens=response.completion_tokens,
            reasoning_suppressed=response.reasoning_suppressed,
        )


@dataclass(frozen=True)
class SQLGeneration:
    """A generated SQL candidate plus its telemetry."""

    sql: str
    meta: GenerationMeta


class LLMService:
    """Application-level LLM operations."""

    async def generate_sql(
        self,
        schema_context: str,
        fk_relationships: str,
        question: str,
        conversation_context: str = "",
        similar_templates: list[dict] | None = None,
    ) -> SQLGeneration:
        """Translate a natural-language question into a single SQL statement."""
        system_prompt, user_prompt = build_sql_prompt(
            schema_context=schema_context,
            fk_relationships=fk_relationships,
            question=question,
            conversation_context=conversation_context,
            similar_templates=similar_templates,
        )
        response = await self._complete(user_prompt, system_prompt, 0.1, 512)
        return SQLGeneration(
            sql=response.text,
            meta=GenerationMeta.from_response(response),
        )

    async def correct_sql(
        self,
        schema_context: str,
        question: str,
        failed_sql: str,
        error_message: str,
    ) -> SQLGeneration:
        """Ask the model to repair a query that failed validation or execution."""
        system_prompt, user_prompt = build_retry_prompt(
            schema_context=schema_context,
            question=question,
            failed_sql=failed_sql,
            error_message=error_message,
        )
        response = await self._complete(user_prompt, system_prompt, 0.1, 640)
        return SQLGeneration(
            sql=response.text,
            meta=GenerationMeta.from_response(response),
        )

    async def generate_suggestions(self, schema_context: str) -> list[str]:
        """Propose analytical questions that suit the current schema."""
        system_prompt, user_prompt = build_suggestion_prompt(schema_context)
        response = await self._complete(user_prompt, system_prompt, 0.3, 512)

        suggestions: list[str] = []
        for line in response.text.splitlines():
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            clean = line.lstrip("0123456789.)- ").strip()
            if clean:
                suggestions.append(clean)

        return suggestions[:8] or list(FALLBACK_SUGGESTIONS)

    async def health(self) -> ProviderHealth:
        """Readiness probe for the configured provider."""
        return await get_llm_provider().health()

    @property
    def model(self) -> str:
        return get_llm_provider().model

    @property
    def provider_name(self) -> str:
        return get_llm_provider().name

    # ── Internals ─────────────────────────────────────────────

    async def _complete(
        self,
        user_prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """Call the provider and re-assert the no-reasoning invariant."""
        provider = get_llm_provider()
        response = await provider.generate(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Second, independent sanitation pass. The provider already did this; a
        # provider that ever stops doing it must still not be able to leak.
        sanitized = strip_reasoning(response.text)
        if sanitized.was_modified:
            logger.warning(
                "Service-layer sanitizer removed residual reasoning markers "
                "from a provider response."
            )
            response = LLMResponse(
                text=sanitized.text,
                model=response.model,
                finish_reason=response.finish_reason,
                prompt_tokens=response.prompt_tokens,
                completion_tokens=response.completion_tokens,
                latency_ms=response.latency_ms,
                reasoning_suppressed=True,
                metadata=response.metadata,
            )

        logger.debug(
            f"LLM call complete: {response.completion_tokens} tokens, "
            f"{response.latency_ms:.0f}ms, model={response.model}"
        )
        return response


# Singleton — import this everywhere
llm_service = LLMService()
