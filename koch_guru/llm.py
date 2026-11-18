"""Thin wrapper around OpenRouter (OpenAI-compatible API). Prompts live in the services."""

from __future__ import annotations

from typing import Any, TypeVar

from openai import APITimeoutError, AsyncOpenAI, LengthFinishReasonError
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Claude Sonnet 5.5 always thinks before it answers, and on OpenRouter the thinking counts
# against max_tokens. The limit therefore covers thinking plus the answer; only the tokens
# actually used are billed.
MAX_TOKENS = 16_000
TIMEOUT_SECONDS = 120


class ModelError(RuntimeError):
    """The model gave no usable answer. The message is short German text for the user."""


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
            timeout=TIMEOUT_SECONDS,
        )
        return cls(client, model)

    async def structured(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        output_type: type[T],
        max_tokens: int = MAX_TOKENS,
    ) -> T:
        """Ask the model for a response that is validated against `output_type`.

        Raises `ModelError` when the answer was cut off, took too long or was refused.
        """
        try:
            completion = await self._client.chat.completions.parse(
                model=self.model,
                messages=[{"role": "system", "content": system}, *messages],
                response_format=output_type,
                max_tokens=max_tokens,
                # Only route to providers that enforce the JSON schema.
                extra_body={"provider": {"require_parameters": True}},
            )
        except LengthFinishReasonError as exc:
            raise ModelError("Die Antwort war zu lang und wurde abgeschnitten.") from exc
        except APITimeoutError as exc:
            raise ModelError("Das hat zu lange gedauert. Versuch es gleich noch einmal.") from exc
        choice = completion.choices[0]
        if choice.message.parsed is None:
            reason = choice.message.refusal or choice.finish_reason
            raise ModelError(f"Das Modell hat keine gültige Antwort geliefert ({reason}).")
        return choice.message.parsed

    async def close(self) -> None:
        await self._client.close()
