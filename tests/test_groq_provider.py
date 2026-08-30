"""
Groq provider tests.

These exercise the parts of the provider that must hold regardless of what the
network does: the request it builds, the way it reads a completion, and the fact
that a ``reasoning`` field in the payload has no path to the returned object.
"""

import httpx
import pytest

from app.llm.base import (
    LLMAuthError,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMResponseError,
)
from app.llm.groq_provider import GroqProvider

MODEL = "openai/gpt-oss-20b"
ANSWER = "SELECT SUM(total_amount) AS revenue FROM fact_sales LIMIT 1"


def completion(content: str, **message_extra) -> dict:
    """Build a Groq-shaped chat completion payload."""
    return {
        "model": MODEL,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content, **message_extra},
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 32},
    }


def provider_with(handler) -> GroqProvider:
    """A provider whose real HTTP client is backed by a mock transport."""
    return GroqProvider(
        api_key="test-key",
        base_url="https://groq.test/openai/v1",
        transport=httpx.MockTransport(handler),
    )


class TestRequestConstruction:
    @pytest.mark.asyncio
    async def test_request_asks_groq_to_hide_reasoning(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen.update(json.loads(request.content))
            return httpx.Response(200, json=completion(ANSWER))

        await provider_with(handler).generate("question", "system", max_tokens=512)

        assert seen["model"] == MODEL
        assert seen["reasoning_format"] == "hidden"
        assert seen["reasoning_effort"] in {"low", "medium", "high"}
        assert seen["stream"] is False, "streaming would risk relaying analysis tokens"
        # Reasoning tokens are billed against the completion budget, so the
        # provider must ask for more than the visible-answer budget.
        assert seen["max_completion_tokens"] > 512
        assert [m["role"] for m in seen["messages"]] == ["system", "user"]

    @pytest.mark.asyncio
    async def test_api_key_travels_in_the_authorization_header_only(self):
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers.get("authorization")
            seen["url"] = str(request.url)
            return httpx.Response(200, json=completion(ANSWER))

        await provider_with(handler).generate("question")

        assert seen["auth"] == "Bearer test-key"
        assert "test-key" not in seen["url"]


class TestReasoningIsNeverReturned:
    @pytest.mark.asyncio
    async def test_reasoning_field_is_ignored(self):
        payload = completion(ANSWER, reasoning="The user wants total revenue, so...")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        response = await provider_with(handler).generate("question")

        assert response.text == ANSWER
        assert "The user wants" not in repr(response)
        assert not hasattr(response, "reasoning")

    @pytest.mark.asyncio
    async def test_think_tags_inside_content_are_stripped(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json=completion(f"<think>deliberating</think>{ANSWER}")
            )

        response = await provider_with(handler).generate("question")

        assert response.text == ANSWER
        assert response.reasoning_suppressed is True

    @pytest.mark.asyncio
    async def test_reasoning_only_completion_is_rejected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=completion("<think>no answer</think>"))

        with pytest.raises(LLMResponseError):
            await provider_with(handler).generate("question")


class TestErrorMapping:
    @pytest.mark.asyncio
    async def test_missing_key_raises_configuration_error(self):
        provider = GroqProvider(api_key="", base_url="https://groq.test/openai/v1")
        with pytest.raises(LLMConfigurationError):
            await provider.generate("question")

    @pytest.mark.asyncio
    async def test_401_raises_auth_error_without_echoing_the_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "Invalid API Key"}})

        with pytest.raises(LLMAuthError) as excinfo:
            await provider_with(handler).generate("question")

        assert "test-key" not in str(excinfo.value)

    @pytest.mark.asyncio
    async def test_429_raises_rate_limit_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": {"message": "rate limit"}})

        provider = provider_with(handler)
        with pytest.raises(LLMRateLimitError):
            await provider.generate("question")

    @pytest.mark.asyncio
    async def test_reasoning_params_are_dropped_when_rejected(self):
        calls: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            calls.append(body)
            if "reasoning_format" in body:
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "message": "unsupported parameter: reasoning_format"
                        }
                    },
                )
            return httpx.Response(200, json=completion(ANSWER))

        response = await provider_with(handler).generate("question")

        assert response.text == ANSWER
        assert len(calls) == 2
        assert "reasoning_format" not in calls[1]


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_reports_missing_key(self):
        provider = GroqProvider(api_key="", base_url="https://groq.test/openai/v1")
        health = await provider.health()
        assert health.available is False
        assert "GROQ_API_KEY" in health.detail

    @pytest.mark.asyncio
    async def test_health_reports_connected(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": MODEL}]})

        health = await provider_with(handler).health()
        assert health.available is True
        assert health.model == MODEL
