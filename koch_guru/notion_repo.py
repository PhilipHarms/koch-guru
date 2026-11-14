"""Read access to the recipe database in Notion.

Uses the data source API (Notion-Version 2025-09-03, notion-client 3.x).
All knowledge about Notion property names and types lives in this module.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from notion_client import APIErrorCode, APIResponseError, AsyncClient
from notion_client.helpers import async_collect_paginated_api, extract_notion_id

from koch_guru.config import PropertyNames
from koch_guru.models import Recipe

log = logging.getLogger(__name__)

LIST_TYPES = {"multi_select", "select", "rich_text"}


@dataclass(frozen=True)
class PropertyMapping:
    """Which Notion property feeds which recipe field (None = not available)."""

    title: str
    link: str | None
    tags: str | None
    ingredients: str | None


def resolve_mapping(schema: dict[str, dict[str, Any]], wanted: PropertyNames) -> PropertyMapping:
    """Map the data source schema to recipe fields.

    The title property is detected by type (every data source has exactly one).
    For the link, the configured name wins; otherwise the first URL property is used.
    Tags and ingredients are only used if the configured property exists with a usable type.
    """
    types = {name: prop.get("type") for name, prop in schema.items()}

    title = next((name for name, t in types.items() if t == "title"), None)
    if title is None:
        raise RuntimeError("Die Notion-Datenbank hat keine Titel-Property.")

    if types.get(wanted.link) == "url":
        link = wanted.link
    else:
        link = next((name for name, t in types.items() if t == "url"), None)

    tags = wanted.tags if types.get(wanted.tags) in LIST_TYPES else None
    ingredients = wanted.ingredients if types.get(wanted.ingredients) in LIST_TYPES else None
    return PropertyMapping(title=title, link=link, tags=tags, ingredients=ingredients)


def _plain_text(rich_text: list[dict[str, Any]] | None) -> str:
    return "".join(part.get("plain_text", "") for part in rich_text or []).strip()


def _list_values(prop: dict[str, Any] | None) -> tuple[str, ...]:
    if not prop:
        return ()
    kind = prop.get("type")
    if kind == "multi_select":
        return tuple(opt["name"] for opt in prop.get("multi_select") or [])
    if kind == "select":
        option = prop.get("select")
        return (option["name"],) if option else ()
    if kind == "rich_text":
        text = _plain_text(prop.get("rich_text"))
        return (text,) if text else ()
    return ()


def page_to_recipe(page: dict[str, Any], mapping: PropertyMapping) -> Recipe | None:
    """Convert a Notion page into a Recipe. Returns None for rows without a name."""
    props = page.get("properties", {})
    name = _plain_text(props.get(mapping.title, {}).get("title"))
    if not name:
        return None

    url = None
    if mapping.link:
        url = (props.get(mapping.link) or {}).get("url") or None

    return Recipe(
        id=page["id"],
        name=name,
        notion_url=page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}",
        url=url,
        tags=_list_values(props.get(mapping.tags)) if mapping.tags else (),
        ingredients=_list_values(props.get(mapping.ingredients)) if mapping.ingredients else (),
    )


class RecipeRepository:
    def __init__(
        self,
        client: AsyncClient,
        database_id: str,
        wanted: PropertyNames,
        cache_seconds: int = 300,
    ) -> None:
        self._client = client
        self._database_id = extract_notion_id(database_id) or database_id
        self._wanted = wanted
        self._cache_seconds = cache_seconds
        self._data_source_id: str | None = None
        self._mapping: PropertyMapping | None = None
        self._cache: list[Recipe] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def mapping(self) -> PropertyMapping | None:
        return self._mapping

    async def connect(self) -> PropertyMapping:
        """Resolve the data source behind NOTION_DATABASE_ID and read its schema."""
        self._data_source_id = await self._resolve_data_source_id()
        data_source = await self._client.data_sources.retrieve(data_source_id=self._data_source_id)
        self._mapping = resolve_mapping(data_source.get("properties", {}), self._wanted)
        log.info(
            "Notion verbunden: Titel=%r, Link=%r, Tags=%r, Zutaten=%r",
            self._mapping.title,
            self._mapping.link,
            self._mapping.tags,
            self._mapping.ingredients,
        )
        return self._mapping

    async def _resolve_data_source_id(self) -> str:
        try:
            database = await self._client.databases.retrieve(database_id=self._database_id)
        except APIResponseError as exc:
            if exc.code != APIErrorCode.ObjectNotFound:
                raise
            # The configured ID may already be a data source ID.
            await self._client.data_sources.retrieve(data_source_id=self._database_id)
            return self._database_id

        sources = database.get("data_sources") or []
        if not sources:
            raise RuntimeError("Die Notion-Datenbank enthält keine Datenquelle.")
        if len(sources) > 1:
            log.warning(
                "Datenbank hat %d Datenquellen, verwende die erste (%s).",
                len(sources),
                sources[0].get("name"),
            )
        return sources[0]["id"]

    async def list_recipes(self, *, force_refresh: bool = False) -> list[Recipe]:
        """All recipes, cached for `cache_seconds`."""
        async with self._lock:
            fresh = time.monotonic() - self._cached_at < self._cache_seconds
            if self._cache is not None and fresh and not force_refresh:
                return self._cache

            if self._mapping is None:
                await self.connect()
            assert self._data_source_id and self._mapping

            pages = await async_collect_paginated_api(
                self._client.data_sources.query,
                data_source_id=self._data_source_id,
                page_size=100,
            )
            recipes = [
                recipe
                for page in pages
                if page.get("object") == "page"
                and (recipe := page_to_recipe(page, self._mapping)) is not None
            ]
            recipes.sort(key=lambda r: r.name.casefold())
            self._cache, self._cached_at = recipes, time.monotonic()
            log.info("%d Rezepte aus Notion geladen.", len(recipes))
            return recipes
