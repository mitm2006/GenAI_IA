"""
Provider-agnostic contract for the LLM layer.

Everything above this module (the LLM service layer, the API routes, the
frontend) depends only on :class:`LLMProvider` and :class:`LLMResponse`. Swapping
Groq for another hosted provider therefore means adding one file and changing
one setting — no route, service or component has to be rewritten.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Error taxonomy ────────────────────────────────────────────
# Each error maps onto a distinct HTTP status at the API boundary, so the
# frontend can render a meaningful state instead of a generic "500".

class LLMError(RuntimeError):
    """Base class for every recoverable LLM failure."""

    http_status: int = 502
    code: str = "llm_error"


class LLMConfigurationError(LLMError):
    """The provider is not usable because configuration/credentials are missing."""

    http_status = 503
    code = "llm_not_configured"


class LLMAuthError(LLMError):
    """The provider rejected our credentials (401/403)."""

    http_status = 502
    code = "llm_auth_failed"


class LLMRateLimitError(LLMError):
    """The provider throttled us (429)."""

    http_status = 429
    code = "llm_rate_limited"


class LLMTimeoutError(LLMError):
    """The provider did not answer within the configured timeout."""

    http_status = 504
    code = "llm_timeout"


class LLMResponseError(LLMError):
    """The provider answered, but the payload was unusable/empty."""

    http_status = 502
    code = "llm_bad_response"


@dataclass(frozen=True)
class LLMResponse:
    """
    A completed generation.

    ``text`` is the *only* field that may ever reach the client. It has already
    passed through the reasoning sanitizer, so it never carries chain-of-thought,
    analysis channels or thinking tags. Any reasoning the provider produced is
    discarded at parse time and is deliberately not represented here — there is
    no field on this object that could leak it.
    """

    text: str
    model: str
    finish_reason: str = "stop"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    reasoning_suppressed: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    """Result of a provider readiness probe."""

    available: bool
    provider: str
    model: str
    detail: str = ""


class LLMProvider(ABC):
    """Interface every LLM provider implementation must satisfy."""

    name: str = "provider"

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifier of the model this provider is configured to call."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Produce a final, user-safe completion for ``prompt``."""

    @abstractmethod
    async def health(self) -> ProviderHealth:
        """Cheap readiness probe used by ``GET /api/health``."""

    async def aclose(self) -> None:  # pragma: no cover - default no-op
        """Release transport resources held by the provider."""
