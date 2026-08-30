"""
Groq provider — hosted inference over Groq's OpenAI-compatible REST API.

Design notes
------------
* **Asynchronous.** A single shared :class:`httpx.AsyncClient` with connection
  pooling is reused for the process lifetime, so the FastAPI event loop is never
  blocked while a completion is in flight.
* **Non-streaming.** The backend deliberately does not stream. A reasoning-capable
  model interleaves analysis and answer tokens, so a naive token relay is the
  easiest way to leak chain-of-thought. Requesting the completed message and
  returning only its final channel removes that class of bug entirely.
* **Reasoning suppression at the source.** Requests carry
  ``reasoning_format="hidden"``, which makes Groq omit the ``reasoning`` field
  altogether. If the parameter is rejected (older deployment, different model),
  the provider retries once without it and relies on the parser + sanitizer.
* **Credentials stay here.** The API key is read from settings (env only) and is
  never logged, never returned in an error payload, and never sent to the client.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from loguru import logger

from app.config import settings
from app.llm.base import (
    LLMAuthError,
    LLMConfigurationError,
    LLMError,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    ProviderHealth,
)
from app.llm.sanitizer import contains_reasoning_markers, strip_reasoning

# Reasoning tokens are billed against ``max_completion_tokens``. Give the model
# room to think privately so the *visible* answer is never truncated.
_REASONING_HEADROOM = {"low": 512, "medium": 1024, "high": 2048}

_RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class GroqProvider(LLMProvider):
    """LLM provider backed by Groq-hosted models."""

    name = "groq"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.groq_api_key).strip()
        self._base_url = (base_url or settings.groq_base_url).rstrip("/")
        self._model = model or settings.llm_model
        self._reasoning_format = settings.llm_reasoning_format
        self._reasoning_effort = settings.llm_reasoning_effort
        # Injectable so tests can exercise the real client setup (headers,
        # timeouts, retry loop) against a mock transport.
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._client_lock = asyncio.Lock()
        # Flipped to False if the deployment rejects the reasoning parameters.
        self._supports_reasoning_params = True

    # ── Public API ────────────────────────────────────────────

    @property
    def model(self) -> str:
        return self._model

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Return a sanitized, user-safe completion."""
        self._require_credentials()

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": settings.llm_temperature if temperature is None else temperature,
            "max_completion_tokens": self._completion_budget(max_tokens),
            "top_p": 0.9,
            "stream": False,
        }
        if self._supports_reasoning_params:
            payload["reasoning_format"] = self._reasoning_format
            payload["reasoning_effort"] = self._reasoning_effort

        started = time.perf_counter()
        data = await self._post_with_retries("/chat/completions", payload)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        return self._parse_completion(data, latency_ms)

    async def health(self) -> ProviderHealth:
        """Verify credentials and that the configured model is reachable."""
        if not self._api_key:
            return ProviderHealth(
                available=False,
                provider=self.name,
                model=self._model,
                detail="GROQ_API_KEY is not set",
            )
        try:
            client = await self._get_client()
            response = await client.get("/models", timeout=httpx.Timeout(10.0))
            if response.status_code in (401, 403):
                return ProviderHealth(False, self.name, self._model, "invalid API key")
            response.raise_for_status()
            ids = {m.get("id") for m in response.json().get("data", [])}
            if ids and self._model not in ids:
                return ProviderHealth(
                    available=False,
                    provider=self.name,
                    model=self._model,
                    detail=f"model {self._model} is not available on this account",
                )
            return ProviderHealth(True, self.name, self._model, "connected")
        except httpx.HTTPError as exc:
            return ProviderHealth(
                False, self.name, self._model, f"unreachable: {type(exc).__name__}"
            )

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ── Internals ─────────────────────────────────────────────

    def _require_credentials(self) -> None:
        if not self._api_key:
            raise LLMConfigurationError(
                "GROQ_API_KEY is not configured. Set it in the environment "
                "(or .env) before starting the API server."
            )

    def _completion_budget(self, max_tokens: int) -> int:
        """Answer budget plus private-reasoning headroom."""
        if not self._supports_reasoning_params:
            return max(max_tokens, 256)
        headroom = _REASONING_HEADROOM.get(self._reasoning_effort, 512)
        return max(max_tokens, 256) + headroom

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        base_url=self._base_url,
                        timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        limits=httpx.Limits(
                            max_connections=20, max_keepalive_connections=10
                        ),
                        transport=self._transport,
                    )
        return self._client

    async def _post_with_retries(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST with bounded retries on transient failures."""
        client = await self._get_client()
        attempts = max(1, settings.llm_max_attempts)
        last_error: LLMError | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await client.post(path, json=payload)
            except httpx.TimeoutException as exc:
                last_error = LLMTimeoutError(
                    f"Groq did not respond within {settings.llm_timeout_seconds:.0f}s."
                )
                logger.warning(f"LLM timeout (attempt {attempt}/{attempts}): {exc!r}")
            except httpx.HTTPError as exc:
                last_error = LLMError(f"Could not reach Groq: {type(exc).__name__}")
                logger.warning(
                    f"LLM transport error (attempt {attempt}/{attempts}): {exc!r}"
                )
            else:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise LLMResponseError(
                            "Groq returned a malformed JSON body."
                        ) from exc

                error = self._classify_error(response, payload)
                if error is None:
                    # Reasoning parameters were rejected — retry without them.
                    continue
                if response.status_code not in _RETRYABLE_STATUS or attempt == attempts:
                    raise error
                last_error = error

            if attempt < attempts:
                await asyncio.sleep(min(2 ** (attempt - 1) * 0.5, 4.0))

        raise last_error or LLMError("Groq request failed.")

    def _classify_error(
        self, response: httpx.Response, payload: dict[str, Any]
    ) -> LLMError | None:
        """
        Map an HTTP error onto a typed :class:`LLMError`.

        Returns ``None`` when the caller should transparently retry because the
        reasoning parameters have just been stripped from ``payload``.
        """
        status = response.status_code
        detail = self._error_detail(response)

        if (
            status == 400
            and self._supports_reasoning_params
            and ("reasoning_format" in detail or "reasoning_effort" in detail)
        ):
            logger.warning(
                "Groq rejected the reasoning parameters; falling back to "
                "server-side reasoning stripping only."
            )
            self._supports_reasoning_params = False
            payload.pop("reasoning_format", None)
            payload.pop("reasoning_effort", None)
            payload["max_completion_tokens"] = max(
                256, int(payload.get("max_completion_tokens", 1024)) - 512
            )
            return None

        if status in (401, 403):
            logger.error(f"Groq rejected the API key (HTTP {status}).")
            return LLMAuthError(
                "Groq rejected the configured API key. Check GROQ_API_KEY."
            )
        if status == 404:
            return LLMConfigurationError(
                f"Model {self._model} was not found on Groq. Check LLM_MODEL."
            )
        if status == 429:
            return LLMRateLimitError(
                "Groq rate limit reached. Please retry in a few seconds."
            )
        if status >= 500:
            return LLMError(f"Groq is temporarily unavailable (HTTP {status}).")

        logger.error(f"Groq request failed with HTTP {status}: {detail[:300]}")
        return LLMError(f"Groq request failed (HTTP {status}): {detail[:200]}")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Extract a provider error message without echoing credentials."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message", ""))[:500]
        return str(error or body)[:500]

    def _parse_completion(self, data: dict[str, Any], latency_ms: float) -> LLMResponse:
        """
        Extract the final answer.

        Only ``message.content`` is read. Sibling fields such as ``reasoning`` or
        ``reasoning_content`` are never touched, never logged and never copied
        into :class:`LLMResponse` — there is no path from them to the client.
        """
        choices = data.get("choices") or []
        if not choices:
            raise LLMResponseError("Groq returned no completion choices.")

        choice = choices[0] or {}
        message = choice.get("message") or {}
        finish_reason = str(choice.get("finish_reason") or "stop")
        raw_content = message.get("content") or ""

        provider_hid_reasoning = not any(
            key in message for key in ("reasoning", "reasoning_content")
        )

        sanitized = strip_reasoning(raw_content)
        if sanitized.was_modified:
            logger.warning(
                "Reasoning markers were present in the completion body and were "
                "removed before the response left the LLM layer."
            )

        text = sanitized.text
        if not text:
            if finish_reason == "length":
                raise LLMResponseError(
                    "The model ran out of output budget before producing a final "
                    "answer. Try a simpler question."
                )
            raise LLMResponseError("The model returned an empty final answer.")

        # Defence in depth: refuse to emit anything that still looks like reasoning.
        if contains_reasoning_markers(text):
            logger.error("Sanitized text still contains reasoning markers — rejecting.")
            raise LLMResponseError("The model response could not be safely processed.")

        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(data.get("model") or self._model),
            finish_reason=finish_reason,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            reasoning_suppressed=provider_hid_reasoning or sanitized.was_modified,
            metadata={"provider": self.name},
        )
