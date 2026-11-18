"""LLMClient against the real openai SDK with a mocked OpenRouter endpoint."""

import json

import httpx2  # the openai SDK uses httpx2, not httpx
import pytest
from openai import AsyncOpenAI

from koch_guru.llm import MAX_TOKENS, OPENROUTER_BASE_URL, TIMEOUT_SECONDS, LLMClient, ModelError
from koch_guru.services.recommend import Selection


def make_client(handler):
    sdk = AsyncOpenAI(
        api_key="sk-or-test",
        base_url=OPENROUTER_BASE_URL,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    )
    return LLMClient(sdk, model="anthropic/claude-sonnet-5.5")


def completion(content, finish_reason="stop"):
    return {
        "id": "gen-1", "object": "chat.completion", "created": 0, "model": "anthropic/claude-sonnet-5.5",
        "choices": [{"index": 0, "finish_reason": finish_reason,
                     "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


async def test_structured_request_and_parsing():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        answer = {"antwort": "Passt!", "rezepte": [{"nr": 2, "grund": "schnell"}]}
        return httpx2.Response(200, json=completion(json.dumps(answer)))

    result = await make_client(handler).structured(
        system="sys", messages=[{"role": "user", "content": "hallo"}], output_type=Selection
    )

    assert result.rezepte[0].nr == 2
    body = captured["body"]
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-or-test"
    assert body["model"] == "anthropic/claude-sonnet-5.5"
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hallo"}]
    assert body["provider"] == {"require_parameters": True}
    assert body["max_tokens"] == MAX_TOKENS  # room for the thinking that Sonnet 5.5 always does
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert set(fmt["json_schema"]["schema"]["required"]) == {"antwort", "rezepte"}


def test_openrouter_client_defaults():
    llm = LLMClient.for_openrouter("sk-or-x", "anthropic/claude-sonnet-5.5")
    assert str(llm._client.base_url).rstrip("/") == OPENROUTER_BASE_URL
    assert llm._client.default_headers["X-Title"] == "KochGuru"
    assert llm._client.timeout == TIMEOUT_SECONDS


async def test_cut_off_answer_is_a_model_error():
    """Thinking counts against max_tokens; a cut-off answer must not end as an unexplained 502."""
    def handler(request):
        return httpx2.Response(200, json=completion('{"antwort": "Pas', finish_reason="length"))

    with pytest.raises(ModelError, match="zu lang"):
        await make_client(handler).structured(
            system="sys", messages=[{"role": "user", "content": "hallo"}], output_type=Selection
        )
