"""Thin wrapper around the Claude API. Prompts live in the services, not here."""

from __future__ import annotations

from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, client: AsyncAnthropic, model: str, effort: str) -> None:
        self._client = client
        self.model = model
        self.effort = effort

    async def structured(
        self,
        *,
        system: str,
        user: str,
        output_type: type[T],
        max_tokens: int = 4096,
    ) -> T:
        """Ask Claude for a response that is validated against `output_type`."""
        response = await self._client.messages.parse(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=output_type,
            output_config={"effort": self.effort},
        )
        if response.parsed_output is None:
            raise RuntimeError(f"Claude hat keine gültige Antwort geliefert ({response.stop_reason}).")
        return response.parsed_output

    async def close(self) -> None:
        await self._client.close()
