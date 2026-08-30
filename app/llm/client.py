"""
LLM provider factory.

The rest of the application never imports a concrete provider. It asks this
module for "the" provider and receives something that satisfies
:class:`~app.llm.base.LLMProvider`. Adding a second hosted backend later is a
matter of writing one class and registering it here.
"""

from __future__ import annotations

from typing import Callable

from loguru import logger

from app.config import settings
from app.llm.base import LLMConfigurationError, LLMProvider
from app.llm.groq_provider import GroqProvider

# name → factory
_REGISTRY: dict[str, Callable[[], LLMProvider]] = {
    "groq": GroqProvider,
}

_provider: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """Return the process-wide provider singleton, creating it on first use."""
    global _provider
    if _provider is None:
        name = (settings.llm_provider or "groq").strip().lower()
        factory = _REGISTRY.get(name)
        if factory is None:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER '{name}'. Available: {sorted(_REGISTRY)}"
            )
        _provider = factory()
        logger.info(f"🤖 LLM provider: {name} (model: {_provider.model})")
    return _provider


def register_provider(name: str, factory: Callable[[], LLMProvider]) -> None:
    """Register an additional provider implementation."""
    _REGISTRY[name.strip().lower()] = factory


async def close_llm_provider() -> None:
    """Release the provider's transport resources (called on app shutdown)."""
    global _provider
    if _provider is not None:
        await _provider.aclose()
        _provider = None
