"""LLMClient against the real Anthropic SDK with a mocked HTTP transport."""

import json

import httpx2  # the Anthropic SDK uses httpx2, not httpx
from anthropic import AsyncAnthropic

from koch_guru.llm import LLMClient
from koch_guru.services.recommend import Selection


async def test_structured_request_and_parsing():
    captured = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        answer = {"antwort": "Passt!", "rezepte": [{"nr": 2, "grund": "schnell"}]}
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [{"type": "text", "text": json.dumps(answer)}],
            "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    sdk = AsyncAnthropic(api_key="test", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    llm = LLMClient(sdk, model="claude-sonnet-5-5", effort="medium")

    result = await llm.structured(system="sys", user="hallo", output_type=Selection)

    assert result.rezepte[0].nr == 2
    body = captured["body"]
    assert captured["path"] == "/v1/messages"
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == "sys"
    assert body["output_config"]["effort"] == "medium"
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert set(fmt["schema"]["required"]) == {"antwort", "rezepte"}
