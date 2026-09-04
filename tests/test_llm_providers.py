"""OpenAI-compatible planner client and provider presets (no network)."""

from __future__ import annotations

import json

import httpx
import pytest

from ml4gw_agent.errors import PlanningError
from ml4gw_agent.llm_planner import (
    PROVIDERS,
    AnthropicClient,
    OpenAICompatibleClient,
    build_client,
    provider_status,
)

SCHEMA = {"type": "object", "properties": {"tasks": {"type": "array"}}}


def _transport(handler):
    return httpx.MockTransport(handler)


def test_json_schema_then_json_object_fallback_and_fences():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body.get("response_format", {}).get("type"))
        assert request.headers["authorization"] == "Bearer k"
        if body.get("response_format", {}).get("type") == "json_schema":
            return httpx.Response(400, json={"error": "response_format unsupported"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '```json\n{"tasks": []}\n```'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )

    client = OpenAICompatibleClient(
        base_url="http://fake/v1", model="m", api_key="k", transport=_transport(handler)
    )
    assert client.complete("sys", "user", SCHEMA) == '{"tasks": []}'
    assert seen == ["json_schema", "json_object"]
    assert client.last_usage == {"input_tokens": 12, "output_tokens": 3}
    # the accepted mode is remembered for the next call
    client.complete("sys", "user", SCHEMA)
    assert seen[-1] == "json_object"


def test_retries_on_overload_then_fails(monkeypatch):
    monkeypatch.setattr("ml4gw_agent.llm_planner.time.sleep", lambda s: None)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503, text="busy")

    client = OpenAICompatibleClient(
        base_url="http://fake/v1", model="m", retries=2, transport=_transport(handler)
    )
    with pytest.raises(PlanningError, match="503"):
        client.complete("sys", "user", SCHEMA)
    assert len(calls) == 2


def test_malformed_and_empty_responses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    client = OpenAICompatibleClient(
        base_url="http://fake/v1", model="m", transport=_transport(handler)
    )
    with pytest.raises(PlanningError, match="empty"):
        client.complete("sys", "user", SCHEMA)

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": 1})

    client = OpenAICompatibleClient(
        base_url="http://fake/v1", model="m", transport=_transport(bad)
    )
    with pytest.raises(PlanningError, match="malformed"):
        client.complete("sys", "user", SCHEMA)


def test_build_client_presets_and_keys():
    env = {"DEEPSEEK_API_KEY": "d", "ML4GW_LLM_API_KEY": ""}
    client = build_client("deepseek", environ=env)
    assert isinstance(client, OpenAICompatibleClient)
    assert client.base_url == PROVIDERS["deepseek"]["base_url"]
    assert client.model == "deepseek-chat" and client.api_key == "d"
    assert isinstance(build_client("anthropic", environ=env), AnthropicClient)
    assert build_client("ollama", environ={}).api_key is None
    with pytest.raises(PlanningError, match="no API key"):
        build_client("openrouter", environ={})
    with pytest.raises(PlanningError, match="needs --llm-base-url"):
        build_client("custom", environ={"ML4GW_LLM_API_KEY": "x"})
    custom = build_client("custom", "m", "http://h/v1", "key", environ={})
    assert custom.base_url == "http://h/v1" and custom.api_key == "key"
    with pytest.raises(PlanningError, match="unknown LLM provider"):
        build_client("nope")
    status = provider_status({"GROQ_API_KEY": "g"})
    assert status["groq"] is True and status["ollama"] is True
    assert status["deepseek"] is False and "custom" not in status
