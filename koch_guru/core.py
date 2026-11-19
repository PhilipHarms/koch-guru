"""Shared clients and services used by both the Telegram bot and the web app.

One process holds one Notion client, one recipe repository (with its cache),
one LLM client and one HTTP client. Bot and web app both work on these, so a
change made in one is visible in the other right away.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx
from notion_client import AsyncClient

from koch_guru.config import Settings, display_name
from koch_guru.llm import LLMClient
from koch_guru.notion_repo import RecipeRepository

log = logging.getLogger(__name__)


@dataclass
class Core:
    notion: AsyncClient
    repo: RecipeRepository
    llm: LLMClient
    http: httpx.AsyncClient

    async def start(self) -> None:
        await self.repo.connect()
        log.info("Modell über OpenRouter: %s", self.llm.model)

    async def aclose(self) -> None:
        await self.notion.aclose()
        await self.llm.close()
        await self.http.aclose()


def build_core(settings: Settings) -> Core:
    notion = AsyncClient(auth=settings.notion_token)
    return Core(
        notion=notion,
        repo=RecipeRepository(
            notion,
            settings.notion_database_id,
            settings.properties,
            cache_seconds=settings.recipe_cache_seconds,
            # Everyone with a web login rates recipes on their own.
            people=list(dict.fromkeys(display_name(n) for n in settings.app_users.values())),
        ),
        llm=LLMClient.for_openrouter(settings.openrouter_api_key, settings.model),
        http=httpx.AsyncClient(follow_redirects=True, timeout=20),
    )
