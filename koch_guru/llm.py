"""Thin wrapper around OpenRouter (OpenAI-compatible API). Prompts live in the services."""

from __future__ import annotations

from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class LLMClient:
    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self.model = model

    @classmethod
    def for_openrouter(cls, api_key: str, model: str) -> LLMClient:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            default_headers={"X-Title": "KochGuru"},  # app name in the OpenRouter dashboard
            timeout=60,
        )
        return cls(client, model)

    async def structured(
        self,
        *,
        system: str,
        messages: list[dict[str, str]],
        output_type: type[T],
        max_tokens: int = 2048,
    ) -> T:
        """Ask the model for a response that is validated against `output_type`."""
        completion = await self._client.chat.completions.parse(
            model=self.model,
            messages=[{"role": "system", "content": system}, *messages],
            response_format=output_type,
            max_tokens=max_tokens,
            # Only route to providers that enforce the JSON schema.
            extra_body={"provider": {"require_parameters": True}},
        )
        choice = completion.choices[0]
        if choice.message.parsed is None:
            reason = choice.message.refusal or choice.finish_reason
            raise RuntimeError(f"Das Modell hat keine gültige Antwort geliefert ({reason}).")
        return choice.message.parsed

    async def close(self) -> None:
        await self._client.close()
