"""Access to the recipe database in Notion.

Uses the data source API (Notion-Version 2025-09-03, notion-client 3.x).
All knowledge about Notion property names and types lives in this module.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from notion_client import APIErrorCode, APIResponseError, AsyncClient
from notion_client.helpers import async_collect_paginated_api, extract_notion_id

from koch_guru.config import PropertyNames
from koch_guru.models import Recipe
from koch_guru.services.importer import RecipeDraft, normalize_url

log = logging.getLogger(__name__)

LIST_TYPES = {"multi_select", "select", "rich_text"}
NO_ACCESS = {APIErrorCode.ObjectNotFound, APIErrorCode.RestrictedResource, APIErrorCode.Unauthorized}


@dataclass(frozen=True)
class PropertyMapping:
    """Which Notion property feeds which recipe field (None = not available)."""

    title: str
    link: str | None
    tags: str | None
    ingredients: str | None
    origin: str | None = None
    this_week: str | None = None
    ingredients_kind: Literal["list", "relation"] | None = None
    ingredients_source: dict[str, str] | None = None  # data_source_id / database_id of the relation
    tags_type: str | None = None  # multi_select, select or rich_text
    tag_options: tuple[str, ...] = ()
    origin_type: str | None = None
    origin_options: tuple[str, ...] = ()


def resolve_mapping(schema: dict[str, dict[str, Any]], wanted: PropertyNames) -> PropertyMapping:
    """Map the data source schema to recipe fields.

    The title property is detected by type (every data source has exactly one).
    For the link, the configured name wins; otherwise the first URL property is used.
    All other fields are only used if the configured property exists with a usable type.
    """
    types = {name: prop.get("type") for name, prop in schema.items()}

    title = next((name for name, t in types.items() if t == "title"), None)
    if title is None:
        raise RuntimeError("Die Notion-Datenbank hat keine Titel-Property.")

    if types.get(wanted.link) == "url":
        link = wanted.link
    else:
        link = next((name for name, t in types.items() if t == "url"), None)

    ingredients, kind, source = None, None, None
    if types.get(wanted.ingredients) in LIST_TYPES:
        ingredients, kind = wanted.ingredients, "list"
    elif types.get(wanted.ingredients) == "relation":
        relation = schema[wanted.ingredients].get("relation") or {}
        source = {k: relation[k] for k in ("data_source_id", "database_id") if relation.get(k)}
        if source:
            ingredients, kind = wanted.ingredients, "relation"

    tags = wanted.tags if types.get(wanted.tags) in LIST_TYPES else None
    origin = wanted.origin if types.get(wanted.origin) in LIST_TYPES else None

    return PropertyMapping(
        title=title,
        link=link,
        tags=tags,
        ingredients=ingredients,
        origin=origin,
        this_week=wanted.this_week if types.get(wanted.this_week) == "checkbox" else None,
        ingredients_kind=kind,
        ingredients_source=source,
        tags_type=types.get(tags) if tags else None,
        tag_options=_option_names(schema, tags),
        origin_type=types.get(origin) if origin else None,
        origin_options=_option_names(schema, origin),
    )


def _option_names(schema: dict[str, dict[str, Any]], prop: str | None) -> tuple[str, ...]:
    """Existing options of a select or multi-select property."""
    if not prop:
        return ()
    kind = schema[prop].get("type")
    if kind not in ("multi_select", "select"):
        return ()
    options = (schema[prop].get(kind) or {}).get("options") or []
    return tuple(o["name"] for o in options if o.get("name"))


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


def _page_title(page: dict[str, Any]) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _plain_text(prop.get("title"))
    return ""


def page_to_recipe(
    page: dict[str, Any],
    mapping: PropertyMapping,
    ingredient_names: dict[str, str] | None = None,
) -> Recipe | None:
    """Convert a Notion page into a Recipe. Returns None for rows without a name."""
    props = page.get("properties", {})
    name = _plain_text(props.get(mapping.title, {}).get("title"))
    if not name:
        return None

    url = (props.get(mapping.link) or {}).get("url") or None if mapping.link else None

    ingredients: tuple[str, ...] = ()
    if mapping.ingredients_kind == "list":
        ingredients = _list_values(props.get(mapping.ingredients))
    elif mapping.ingredients_kind == "relation" and ingredient_names:
        # Page objects list at most 25 relations; enough for an ingredient list.
        related = (props.get(mapping.ingredients) or {}).get("relation") or []
        ingredients = tuple(
            ingredient_names[ref["id"]] for ref in related if ref.get("id") in ingredient_names
        )

    return Recipe(
        id=page["id"],
        name=name,
        notion_url=page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}",
        url=url,
        tags=_list_values(props.get(mapping.tags)) if mapping.tags else (),
        origin=_list_values(props.get(mapping.origin)) if mapping.origin else (),
        ingredients=ingredients,
        this_week=bool((props.get(mapping.this_week) or {}).get("checkbox")) if mapping.this_week else False,
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
        self._ingredient_warning_logged = False

    @property
    def mapping(self) -> PropertyMapping | None:
        return self._mapping

    @property
    def supports_this_week(self) -> bool:
        return bool(self._mapping and self._mapping.this_week)

    async def connect(self) -> PropertyMapping:
        """Resolve the data source behind NOTION_DATABASE_ID and read its schema."""
        self._data_source_id = await self._resolve_data_source_id(self._database_id)
        data_source = await self._client.data_sources.retrieve(data_source_id=self._data_source_id)
        self._mapping = resolve_mapping(data_source.get("properties", {}), self._wanted)
        m = self._mapping
        log.info(
            "Notion verbunden: Titel=%r, Link=%r, Tags=%r, Origin=%r, Zutaten=%r (%s), This Week=%r",
            m.title, m.link, m.tags, m.origin, m.ingredients, m.ingredients_kind, m.this_week,
        )
        return self._mapping

    async def _resolve_data_source_id(self, database_id: str) -> str:
        try:
            database = await self._client.databases.retrieve(database_id=database_id)
        except APIResponseError as exc:
            if exc.code != APIErrorCode.ObjectNotFound:
                raise
            # The configured ID may already be a data source ID.
            await self._client.data_sources.retrieve(data_source_id=database_id)
            return database_id

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

    async def _load_ingredient_names(self) -> dict[str, str]:
        """id -> name for all pages of the related ingredients database.

        Needs the ingredients database to be connected to the integration as well.
        Without access, recipes are loaded without ingredients.
        """
        source = self._mapping.ingredients_source if self._mapping else None
        if not source:
            return {}
        try:
            data_source_id = source.get("data_source_id") or await self._resolve_data_source_id(
                source["database_id"]
            )
            pages = await async_collect_paginated_api(
                self._client.data_sources.query, data_source_id=data_source_id, page_size=100
            )
        except APIResponseError as exc:
            if exc.code not in NO_ACCESS:
                raise
            if not self._ingredient_warning_logged:
                log.warning(
                    "Kein Zugriff auf die Zutaten-Datenbank (%s). Verbinde sie in Notion mit der "
                    "Integration, damit der Bot Zutaten kennt.",
                    exc.code,
                )
                self._ingredient_warning_logged = True
            return {}
        names = {p["id"]: name for p in pages if (name := _page_title(p))}
        log.info("%d Zutaten aus Notion geladen.", len(names))
        return names

    async def list_recipes(self, *, force_refresh: bool = False) -> list[Recipe]:
        """All recipes, cached for `cache_seconds`."""
        async with self._lock:
            fresh = time.monotonic() - self._cached_at < self._cache_seconds
            if self._cache is not None and fresh and not force_refresh:
                return self._cache

            if self._mapping is None:
                await self.connect()
            assert self._data_source_id and self._mapping

            ingredient_names = await self._load_ingredient_names()
            pages = await async_collect_paginated_api(
                self._client.data_sources.query,
                data_source_id=self._data_source_id,
                page_size=100,
            )
            recipes = [
                recipe
                for page in pages
                if page.get("object") == "page"
                and (recipe := page_to_recipe(page, self._mapping, ingredient_names)) is not None
            ]
            recipes.sort(key=lambda r: r.name.casefold())
            self._cache, self._cached_at = recipes, time.monotonic()
            log.info("%d Rezepte aus Notion geladen.", len(recipes))
            return recipes

    async def set_this_week(self, page_id: str, value: bool) -> None:
        """Tick or untick the "This Week?" checkbox of a recipe."""
        if not self.supports_this_week:
            raise RuntimeError("Die Notion-Datenbank hat keine Checkbox für die Wochenliste.")
        await self._client.pages.update(
            page_id=page_id, properties={self._mapping.this_week: {"checkbox": value}}
        )
        self._update_cached(page_id, value)

    async def clear_this_week(self) -> int:
        """Untick all recipes on the weekly list. Returns how many were cleared."""
        planned = [r for r in await self.list_recipes(force_refresh=True) if r.this_week]
        for recipe in planned:
            await self.set_this_week(recipe.id, False)
        return len(planned)

    @property
    def tag_options(self) -> list[str]:
        return list(self._mapping.tag_options) if self._mapping else []

    @property
    def origin_options(self) -> list[str]:
        return list(self._mapping.origin_options) if self._mapping else []

    async def find_existing(self, draft: RecipeDraft) -> tuple[Recipe | None, str]:
        """An existing recipe with the same link ("link") or the same name ("name")."""
        name = draft.name.casefold()
        recipes = await self.list_recipes()
        if draft.url:
            target = normalize_url(draft.url)
            for recipe in recipes:
                if recipe.url and normalize_url(recipe.url) == target:
                    return recipe, "link"
        for recipe in recipes:
            if recipe.name.casefold() == name:
                return recipe, "name"
        return None, ""

    async def create_recipe(self, draft: RecipeDraft) -> Recipe:
        if self._mapping is None:
            await self.connect()
        assert self._data_source_id and self._mapping
        kwargs: dict[str, Any] = {
            "parent": {"type": "data_source_id", "data_source_id": self._data_source_id},
            "properties": draft_properties(draft, self._mapping),
            "children": draft_blocks(draft, await self._upload_photos(draft)),
        }
        if draft.image:
            kwargs["cover"] = {"type": "external", "external": {"url": draft.image}}
        if draft.icon:
            kwargs["icon"] = {"type": "emoji", "emoji": draft.icon}
        try:
            page = await self._client.pages.create(**kwargs)
        except APIResponseError as exc:
            # Notion rejects emojis it does not know. Save the recipe anyway, just without icon.
            if exc.code != APIErrorCode.ValidationError or "icon" not in kwargs:
                raise
            log.warning("Notion hat das Icon %r abgelehnt, speichere ohne Icon.", draft.icon)
            kwargs.pop("icon")
            page = await self._client.pages.create(**kwargs)
        self._cache = None  # reload on next access so the new recipe shows up
        recipe = page_to_recipe(page, self._mapping)
        return recipe or Recipe(id=page["id"], name=draft.name, notion_url=page.get("url", ""), url=draft.url)

    async def _upload_photos(self, draft: RecipeDraft) -> list[str]:
        """Upload the original photos to Notion. On failure the recipe is saved without them."""
        ids = []
        try:
            for nr, (data, mime) in enumerate(draft.photos, start=1):
                filename = f"rezept-{nr}.{mime.rsplit('/', 1)[-1].replace('jpeg', 'jpg')}"
                upload = await self._client.file_uploads.create(
                    mode="single_part", filename=filename, content_type=mime
                )
                await self._client.file_uploads.send(
                    file_upload_id=upload["id"], file=(filename, data, mime)
                )
                ids.append(upload["id"])
        except APIResponseError as exc:
            log.warning("Foto-Upload zu Notion fehlgeschlagen (%s), speichere ohne Foto.", exc.code)
            return []
        return ids

    def _update_cached(self, page_id: str, value: bool) -> None:
        if self._cache is None:
            return
        wanted = page_id.replace("-", "")
        self._cache = [
            dataclasses.replace(r, this_week=value) if r.short_id == wanted else r for r in self._cache
        ]


# --- Creating recipes ----------------------------------------------------------------

MAX_BLOCKS = 100
MAX_TEXT = 2000


def _text(content: str, link: str | None = None) -> dict[str, Any]:
    text: dict[str, Any] = {"content": content[:MAX_TEXT]}
    if link:
        text["link"] = {"url": link}
    return {"type": "text", "text": text}


def _block(kind: str, *rich_text: dict[str, Any]) -> dict[str, Any]:
    return {"object": "block", "type": kind, kind: {"rich_text": list(rich_text)}}


def _image_block(file_upload_id: str) -> dict[str, Any]:
    return {"object": "block", "type": "image",
            "image": {"type": "file_upload", "file_upload": {"id": file_upload_id}}}


def draft_blocks(draft: RecipeDraft, photo_upload_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Page content: info line, ingredients, steps, original photos. Capped at Notion's 100 blocks."""
    info = []
    if draft.total_minutes:
        info.append(f"⏱ {draft.total_minutes} Min")
    if draft.servings:
        info.append(f"🍽 {draft.servings}")
    if draft.url:
        source = [_text(" · ".join(info + ["Quelle: "])), _text(draft.site, draft.url)]
    else:
        source = [_text(" · ".join(info + [f"Quelle: {', '.join(draft.origin) or 'Foto'}"]))]
    blocks = [_block("paragraph", *source)]
    blocks.append(_block("heading_2", _text("Zutaten")))
    blocks += [_block("bulleted_list_item", _text(i)) for i in draft.ingredients]
    if draft.steps:
        blocks.append(_block("heading_2", _text("Zubereitung")))
        blocks += [_block("numbered_list_item", _text(s)) for s in draft.steps]

    tail = []
    if photo_upload_ids:
        tail = [_block("heading_2", _text("Originalfoto"))] + [_image_block(i) for i in photo_upload_ids]
    room = MAX_BLOCKS - len(tail)
    if len(blocks) > room:
        note = "Gekürzt, der Rest steht " + ("in der Quelle." if draft.url else "auf dem Foto.")
        blocks = blocks[: room - 1] + [_block("paragraph", _text(note, draft.url or None))]
    return blocks + tail


def draft_properties(draft: RecipeDraft, mapping: PropertyMapping) -> dict[str, Any]:
    props: dict[str, Any] = {mapping.title: {"title": [_text(draft.name)]}}
    if mapping.link and draft.url:
        props[mapping.link] = {"url": draft.url}
    if mapping.tags and draft.tags:
        props[mapping.tags] = _list_property(mapping.tags_type, draft.tags)
    if mapping.origin and draft.origin:
        props[mapping.origin] = _list_property(mapping.origin_type, draft.origin)
    return props


def _list_property(kind: str | None, values: list[str]) -> dict[str, Any]:
    if kind == "multi_select":
        return {"multi_select": [{"name": v} for v in values]}
    if kind == "select":
        return {"select": {"name": values[0]}}
    return {"rich_text": [_text(", ".join(values))]}
