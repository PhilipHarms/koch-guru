"""Access to the recipe database in Notion.

Uses the data source API (Notion-Version 2025-09-03, notion-client 3.x).
All knowledge about Notion property names and types lives in this module.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

from notion_client import APIErrorCode, APIResponseError, AsyncClient
from notion_client.helpers import async_collect_paginated_api, extract_notion_id

from koch_guru.config import PropertyNames
from koch_guru.models import Ingredient, Recipe
from koch_guru.services.importer import RecipeDraft, normalize_url

log = logging.getLogger(__name__)

LIST_TYPES = {"multi_select", "select", "rich_text"}
# Page content: block types whose nested blocks the web app shows, and how far to follow them.
NESTED_TYPES = {
    "bulleted_list_item", "numbered_list_item", "to_do", "toggle", "quote", "callout",
    "column_list", "column", "synced_block",
}
MAX_DEPTH = 3
MAX_CHILD_REQUESTS = 20
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
    last_cooked: str | None = None  # date
    note: str | None = None  # rich_text
    ratings: tuple[tuple[str, str], ...] = ()  # (person, number property)


@dataclass(frozen=True)
class IngredientFields:
    """Properties of the ingredients database that the shopping list uses (None = missing)."""

    bought: str | None = None  # checkbox
    bought_on: str | None = None  # date
    extra: str | None = None  # checkbox
    aisle: str | None = None  # select or multi-select
    aisle_kind: str | None = None  # "select" or "multi_select"
    aisles: tuple[str, ...] = ()  # its options, in the order set in Notion


def _same_name(a: str, b: str) -> bool:
    """Property names match regardless of letter case and a trailing question mark ("Bought?")."""
    return a.casefold().strip().rstrip("?").strip() == b.casefold().strip().rstrip("?").strip()


def _find_property(schema: dict[str, dict[str, Any]], name: str, kind: str) -> str | None:
    """The property called `name` (see `_same_name`) if it has the type `kind`."""
    return next((key for key, prop in schema.items() if _same_name(key, name) and prop.get("type") == kind), None)


def page_to_ingredient(page: dict[str, Any], name: str, fields: IngredientFields) -> Ingredient:
    props = page.get("properties") or {}

    def checkbox(prop: str | None) -> bool:
        return bool((props.get(prop) or {}).get("checkbox")) if prop else False

    date = ((props.get(fields.bought_on) or {}).get("date") or {}) if fields.bought_on else {}
    aisle = None
    if fields.aisle:
        prop = props.get(fields.aisle) or {}
        value = prop.get(prop.get("type", ""))
        options = value if isinstance(value, list) else [value] if isinstance(value, dict) else []
        names = [o.get("name") for o in options if o and o.get("name")]
        # With several tags, the first one in Notion's own order decides.
        names.sort(key=lambda n: fields.aisles.index(n) if n in fields.aisles else len(fields.aisles))
        aisle = names[0] if names else None
    return Ingredient(
        id=page["id"],
        name=name,
        icon=page_icon(page),
        bought=checkbox(fields.bought),
        bought_on=(date.get("start") or "")[:10] or None,
        extra=checkbox(fields.extra),
        aisle=aisle,
    )


def resolve_mapping(
    schema: dict[str, dict[str, Any]], wanted: PropertyNames, people: Sequence[str] = ()
) -> PropertyMapping:
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
        last_cooked=_find_property(schema, wanted.last_cooked, "date"),
        note=_find_property(schema, wanted.note, "rich_text"),
        ratings=tuple(
            (person, prop) for person in people if (prop := _find_property(schema, rating_name(wanted, person), "number"))
        ),
    )


def rating_name(wanted: PropertyNames, person: str) -> str:
    return f"{wanted.rating} {person}"


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
    ingredient_ids: tuple[str, ...] = ()
    if mapping.ingredients_kind == "list":
        ingredients = _list_values(props.get(mapping.ingredients))
    elif mapping.ingredients_kind == "relation" and ingredient_names:
        # Page objects list at most 25 relations; enough for an ingredient list.
        related = (props.get(mapping.ingredients) or {}).get("relation") or []
        ingredient_ids = tuple(ref["id"] for ref in related if ref.get("id") in ingredient_names)
        ingredients = tuple(ingredient_names[i] for i in ingredient_ids)

    return Recipe(
        id=page["id"],
        name=name,
        notion_url=page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}",
        url=url,
        tags=_list_values(props.get(mapping.tags)) if mapping.tags else (),
        origin=_list_values(props.get(mapping.origin)) if mapping.origin else (),
        ingredients=ingredients,
        ingredient_ids=ingredient_ids,
        this_week=bool((props.get(mapping.this_week) or {}).get("checkbox")) if mapping.this_week else False,
        emoji=_page_emoji(page),
        created=page.get("created_time"),
        cover=_page_cover(page),
        last_cooked=((props.get(mapping.last_cooked) or {}).get("date") or {}).get("start", "")[:10] or None
        if mapping.last_cooked else None,
        ratings=tuple(
            (person, int(stars)) for person, prop in mapping.ratings
            if isinstance(stars := (props.get(prop) or {}).get("number"), (int, float)) and 1 <= stars <= 5
        ),
        note=_plain_text((props.get(mapping.note) or {}).get("rich_text")) or None if mapping.note else None,
    )


def _page_emoji(page: dict[str, Any]) -> str | None:
    icon = page.get("icon") or {}
    return icon.get("emoji") if icon.get("type") == "emoji" else None


def page_icon(page: dict[str, Any]) -> str | None:
    """The page icon as an emoji, or as an image address for Notion's own icons and uploads."""
    icon = page.get("icon") or {}
    kind = icon.get("type")
    if kind == "emoji":
        return icon.get("emoji")
    if kind == "icon":  # Notion's built-in icons, e.g. https://www.notion.so/icons/pizza_blue.svg
        data = icon.get("icon") or {}
        name, color = data.get("name"), data.get("color") or "gray"
        return f"https://www.notion.so/icons/{quote(name)}_{quote(color)}.svg" if name else None
    if kind == "custom_emoji":
        return (icon.get("custom_emoji") or {}).get("url")
    if kind in ("external", "file"):
        return (icon.get(kind) or {}).get("url")
    return None


def _page_cover(page: dict[str, Any]) -> str | None:
    cover = page.get("cover") or {}
    kind = cover.get("type")
    return (cover.get(kind) or {}).get("url") or None if kind in ("external", "file") else None


class RecipeRepository:
    def __init__(
        self,
        client: AsyncClient,
        database_id: str,
        wanted: PropertyNames,
        cache_seconds: int = 300,
        people: Sequence[str] = (),
    ) -> None:
        self._client = client
        self._people = tuple(people)  # who rates recipes, e.g. ("Philip", "Charlotte")
        self._database_id = extract_notion_id(database_id) or database_id
        self._wanted = wanted
        self._cache_seconds = cache_seconds
        self._data_source_id: str | None = None
        self._mapping: PropertyMapping | None = None
        self._cache: list[Recipe] | None = None
        self._cached_at = 0.0
        self._lock = asyncio.Lock()
        self._ingredient_warning_logged = False
        self._ingredient_icons: dict[str, str] = {}
        self._ingredient_ids: dict[str, str] = {}  # name -> page id
        self._ingredient_source: tuple[str, str] | None = None  # (data source id, title property)
        self._ingredient_fields: IngredientFields | None = None  # checked once per start
        self._ingredients: dict[str, Ingredient] = {}  # page id -> ingredient
        self._content_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

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
        schema = data_source.get("properties", {})
        self._mapping = resolve_mapping(schema, self._wanted, self._people)
        if await self._add_cooking_fields(schema):
            data_source = await self._client.data_sources.retrieve(data_source_id=self._data_source_id)
            self._mapping = resolve_mapping(data_source.get("properties", {}), self._wanted, self._people)
        m = self._mapping
        log.info(
            "Notion verbunden: Titel=%r, Link=%r, Tags=%r, Origin=%r, Zutaten=%r (%s), This Week=%r",
            m.title, m.link, m.tags, m.origin, m.ingredients, m.ingredients_kind, m.this_week,
        )
        return self._mapping

    async def _add_cooking_fields(self, schema: dict[str, dict[str, Any]]) -> bool:
        """Create "Zuletzt gekocht", "Notiz" and one "Bewertung <Name>" per person if missing.

        A name already used by a property of another type is left alone. Returns whether
        fields were created; without edit access to the schema the app works without them.
        """
        assert self._mapping and self._data_source_id
        w, m = self._wanted, self._mapping

        def taken(name: str) -> bool:
            return any(_same_name(key, name) for key in schema)

        missing: dict[str, dict[str, Any]] = {}
        if m.last_cooked is None and not taken(w.last_cooked):
            missing[w.last_cooked] = {"date": {}}
        if m.note is None and not taken(w.note):
            missing[w.note] = {"rich_text": {}}
        rated = {person for person, _ in m.ratings}
        for person in self._people:
            name = rating_name(w, person)
            if person not in rated and not taken(name):
                missing[name] = {"number": {"format": "number"}}
        if not missing:
            return False
        try:
            await self._client.data_sources.update(data_source_id=self._data_source_id, properties=missing)
        except APIResponseError as exc:
            log.warning("Felder %s nicht angelegt: %s", ", ".join(missing), exc.code)
            return False
        log.info("Felder in der Rezeptdatenbank angelegt: %s", ", ".join(missing))
        return True

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
        fields = await self._ensure_ingredient_fields(data_source_id)
        self._ingredients = {
            p["id"]: page_to_ingredient(p, names[p["id"]], fields) for p in pages if p["id"] in names
        }
        self._ingredient_ids = {name: page_id for page_id, name in names.items()}
        title_prop = next(
            (key for p in pages for key, prop in p.get("properties", {}).items() if prop.get("type") == "title"),
            None,
        )
        self._ingredient_source = (data_source_id, title_prop) if title_prop else None
        self._ingredient_icons = {
            names[p["id"]]: icon for p in pages if p["id"] in names and (icon := page_icon(p))
        }
        kinds = Counter(((p.get("icon") or {}).get("type") or "ohne") for p in pages)
        log.info(
            "%d Zutaten aus Notion geladen. Symbole: %s",
            len(names),
            ", ".join(f"{count} {kind}" for kind, count in kinds.most_common()),
        )
        return names

    async def _ensure_ingredient_fields(self, data_source_id: str) -> IngredientFields:
        """Find Bought, Gekauft am and Extra; create the last two if they are missing.

        Runs once per start. Without edit access to the schema the shopping list still works,
        only without a purchase date and without own items.
        """
        if self._ingredient_fields is not None:
            return self._ingredient_fields
        w = self._wanted
        try:
            source = await self._client.data_sources.retrieve(data_source_id=data_source_id)
        except APIResponseError as exc:
            log.warning("Felder der Zutaten-Datenbank nicht gelesen: %s", exc.code)
            self._ingredient_fields = IngredientFields()
            return self._ingredient_fields
        schema = source.get("properties") or {}
        def taken(name: str) -> bool:
            return any(_same_name(key, name) for key in schema)

        bought = _find_property(schema, w.bought, "checkbox")
        bought_on = _find_property(schema, w.bought_on, "date")
        extra = _find_property(schema, w.extra, "checkbox")
        missing: dict[str, dict[str, Any]] = {}
        if bought_on is None and not taken(w.bought_on):
            missing[w.bought_on] = {"date": {}}
        if extra is None and not taken(w.extra):
            missing[w.extra] = {"checkbox": {}}
        if missing:
            try:
                await self._client.data_sources.update(data_source_id=data_source_id, properties=missing)
            except APIResponseError as exc:
                log.warning("Felder %s nicht angelegt: %s", ", ".join(missing), exc.code)
            else:
                log.info("Felder in der Zutaten-Datenbank angelegt: %s", ", ".join(missing))
                bought_on = bought_on or (w.bought_on if w.bought_on in missing else None)
                extra = extra or (w.extra if w.extra in missing else None)
        if bought is None:
            log.warning("Die Zutaten-Datenbank hat keine Checkbox %r; abhaken geht nicht.", w.bought)
        aisle = _find_property(schema, w.aisle, "multi_select") or _find_property(schema, w.aisle, "select")
        aisles: tuple[str, ...] = ()
        if aisle:
            kind = schema[aisle]["type"]
            aisles = tuple(o["name"] for o in (schema[aisle].get(kind) or {}).get("options") or [] if o.get("name"))
        self._ingredient_fields = IngredientFields(
            bought=bought, bought_on=bought_on, extra=extra, aisle=aisle,
            aisle_kind=schema[aisle]["type"] if aisle else None, aisles=aisles,
        )
        return self._ingredient_fields

    @property
    def ingredient_fields(self) -> IngredientFields:
        return self._ingredient_fields or IngredientFields()

    @property
    def ingredients(self) -> dict[str, Ingredient]:
        """Page id -> ingredient, loaded together with the recipes."""
        return self._ingredients

    async def set_bought(self, ingredient_id: str, value: bool, *, today: str) -> Ingredient:
        """Tick an ingredient off the shopping list, or put it back. Sets "Gekauft am" with it."""
        fields = self.ingredient_fields
        if not fields.bought:
            raise RuntimeError(f"Die Zutaten-Datenbank hat keine Checkbox „{self._wanted.bought}“.")
        current = self._ingredients[ingredient_id]
        props: dict[str, Any] = {fields.bought: {"checkbox": value}}
        if fields.bought_on:
            props[fields.bought_on] = {"date": {"start": today} if value else None}
        await self._client.pages.update(page_id=ingredient_id, properties=props)
        updated = dataclasses.replace(current, bought=value, bought_on=today if value else None)
        self._ingredients[ingredient_id] = updated
        return updated

    async def add_extra(self, name: str) -> Ingredient:
        """Put an own item on the shopping list. An ingredient with that name is reused."""
        fields = self.ingredient_fields
        if not fields.extra or self._ingredient_source is None:
            raise RuntimeError(f"Die Zutaten-Datenbank hat keine Checkbox „{self._wanted.extra}“.")
        props: dict[str, Any] = {fields.extra: {"checkbox": True}}
        if fields.bought:
            props[fields.bought] = {"checkbox": False}
        if fields.bought_on:
            props[fields.bought_on] = {"date": None}
        existing = next((i for i in self._ingredients.values() if i.name.casefold() == name.casefold()), None)
        if existing:
            await self._client.pages.update(page_id=existing.id, properties=props)
            added = dataclasses.replace(existing, extra=True, bought=False, bought_on=None)
        else:
            data_source_id, title_prop = self._ingredient_source
            page = await self._client.pages.create(
                parent={"type": "data_source_id", "data_source_id": data_source_id},
                properties={title_prop: {"title": [_text(name)]}, **props},
            )
            added = Ingredient(id=page["id"], name=name, extra=True)
            self._ingredient_ids[name] = page["id"]
        self._ingredients[added.id] = added
        return added

    @property
    def ingredient_names(self) -> list[str]:
        """All names in the ingredients database."""
        return sorted(self._ingredient_ids, key=str.casefold)

    @property
    def ingredient_icons(self) -> dict[str, str]:
        """Ingredient name -> emoji, or image address of a Notion icon, from the ingredients database."""
        return self._ingredient_icons

    async def page_blocks(self, page_id: str, *, refresh: bool = False) -> list[dict[str, Any]]:
        """Content of a recipe page, with nested blocks under "children". Cached like the list."""
        cached = self._content_cache.get(page_id)
        if cached and not refresh and time.monotonic() - cached[0] < self._cache_seconds:
            return cached[1]
        budget = [MAX_CHILD_REQUESTS]
        blocks = await self._block_children(page_id, 0, budget)
        self._content_cache[page_id] = (time.monotonic(), blocks)
        return blocks

    async def _block_children(self, block_id: str, depth: int, budget: list[int]) -> list[dict[str, Any]]:
        blocks = await async_collect_paginated_api(
            self._client.blocks.children.list, block_id=block_id, page_size=100
        )
        for block in blocks:
            if (
                block.get("has_children")
                and block.get("type") in NESTED_TYPES
                and depth < MAX_DEPTH
                and budget[0] > 0
            ):
                budget[0] -= 1  # each nested block costs a request; keep big pages fast
                block["children"] = await self._block_children(block["id"], depth + 1, budget)
        return blocks

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
                ids.append(await self._upload_file(f"rezept-{nr}", data, mime))
        except APIResponseError as exc:
            log.warning("Foto-Upload zu Notion fehlgeschlagen (%s), speichere ohne Foto.", exc.code)
            return []
        return ids

    async def _upload_file(self, stem: str, data: bytes, mime: str) -> str:
        """Upload a file to Notion; returns the id to attach it to a page or block."""
        filename = f"{stem}.{mime.rsplit('/', 1)[-1].replace('jpeg', 'jpg')}"
        upload = await self._client.file_uploads.create(mode="single_part", filename=filename, content_type=mime)
        await self._client.file_uploads.send(file_upload_id=upload["id"], file=(filename, data, mime))
        return upload["id"]

    async def set_cover_photo(self, page_id: str, data: bytes, mime: str) -> Recipe | None:
        """Upload a photo and make it the page cover. Returns the recipe with the new cover."""
        upload_id = await self._upload_file("titelbild", data, mime)
        page = await self._client.pages.update(
            page_id=page_id, cover={"type": "file_upload", "file_upload": {"id": upload_id}}
        )
        cover = _page_cover(page)
        updated = self._replace_cached(page_id, cover=cover) if cover else None
        if updated is None:
            self._cache = None  # not cached or no address in the answer: read the page again
        return updated

    # --- Filling a page with a generated recipe -------------------------------------

    async def save_generated(
        self,
        page_id: str,
        *,
        draft: RecipeDraft,
        link: list[tuple[str, str | None]],
        cover: str | None = None,
        replace_ids: Sequence[str] = (),
        unlink_ids: Sequence[str] = (),
        new_link: str | None = None,
    ) -> list[str]:
        """Write ingredients and steps to the page, link ingredients and set the cover.

        `cover` is an image address, set as the page cover like an import in the bot does.

        `link` holds (ingredient name, emoji). Names from the ingredients database are
        linked; other names get a new page there first. Links that are already set stay,
        except `unlink_ids`, ingredients of an earlier, wrong version of the recipe.

        `replace_ids` are blocks of an earlier generation (see `generated_sections`): the
        new content goes in their place and they are deleted. Without them it is appended.
        `new_link` replaces the recipe's Link, when it was corrected for this generation.
        Returns the names that could not be created or linked (e.g. without edit access).
        """
        if self._mapping is None:
            await self.connect()
        assert self._mapping
        if new_link and self._mapping.link:
            # First, so a failure leaves the page as it was.
            await self._client.pages.update(page_id=page_id, properties={self._mapping.link: {"url": new_link}})
        if replace_ids:
            await self._client.blocks.children.append(
                block_id=page_id, children=draft_blocks(draft), after=replace_ids[0]
            )
            for block_id in replace_ids:
                try:
                    await self._client.blocks.delete(block_id=block_id)
                except APIResponseError as exc:  # a leftover line is better than a failed save
                    log.warning("Alter Block %s nicht gelöscht: %s", block_id, exc.code)
        else:
            await self._client.blocks.children.append(block_id=page_id, children=draft_blocks(draft))
        if cover:
            try:
                await self._client.pages.update(page_id=page_id, cover={"type": "external", "external": {"url": cover}})
            except APIResponseError as exc:  # a missing photo is no reason to fail the save
                log.warning("Titelbild nicht gesetzt: %s", exc.code)

        not_created = await self.link_ingredients(page_id, link, unlink_ids=unlink_ids)
        self._content_cache.pop(page_id, None)
        self._cache = None  # reload ingredients and links on next access
        return not_created

    async def link_ingredients(
        self, page_id: str, link: Sequence[tuple[str, ...]], *, unlink_ids: Sequence[str] = ()
    ) -> list[str]:
        """Link ingredients to a recipe; names not in the ingredients database get a page first.

        `link` holds (ingredient name, emoji) or (name, emoji, aisle); the aisle tags a new
        ingredient. Links that are already set stay, except `unlink_ids`.
        Returns the names that could not be created or linked.
        """
        if self._mapping is None:
            await self.connect()
        assert self._mapping
        if self._mapping.ingredients_kind != "relation" or not self._mapping.ingredients:
            return []
        if self._ingredient_source is None:
            await self.list_recipes()  # finds the ingredients database and its names
        not_created: list[str] = []
        ids: list[str] = []
        by_key = {name.casefold(): ingredient_id for name, ingredient_id in self._ingredient_ids.items()}
        for name, emoji, *rest in link:
            found = by_key.get(name.casefold())
            if found is None:
                found = await self._create_ingredient(name, emoji, rest[0] if rest else None)
                if found is None:
                    not_created.append(name)
                    continue
                by_key[name.casefold()] = found
            if found not in ids:
                ids.append(found)
        if ids or unlink_ids:
            drop = {i.replace("-", "") for i in unlink_ids}
            try:
                current = await self._relation_ids(page_id, self._mapping.ingredients)
                kept = [i for i in current if i.replace("-", "") not in drop]
                merged = kept + [i for i in ids if i not in kept]
                if merged != current:
                    await self._client.pages.update(
                        page_id=page_id,
                        properties={self._mapping.ingredients: {"relation": [{"id": i} for i in merged]}},
                    )
            except APIResponseError as exc:
                # The content is on the page already; report the links instead of failing.
                log.warning("Zutaten nicht verknüpft: %s", exc.code)
                not_created = [entry[0] for entry in link]
        self._cache = None  # reload ingredients and links on next access
        return not_created

    async def _create_ingredient(self, name: str, emoji: str | None, aisle: str | None = None) -> str | None:
        if self._ingredient_source is None:
            return None
        data_source_id, title_prop = self._ingredient_source
        kwargs: dict[str, Any] = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": {title_prop: {"title": [_text(name)]}},
        }
        fields = self.ingredient_fields
        if aisle and fields.aisle and aisle in fields.aisles:  # only tags that exist
            option = {"name": aisle}
            kwargs["properties"][fields.aisle] = (
                {"multi_select": [option]} if fields.aisle_kind == "multi_select" else {"select": option}
            )
        if emoji:
            kwargs["icon"] = {"type": "emoji", "emoji": emoji}
        try:
            try:
                page = await self._client.pages.create(**kwargs)
            except APIResponseError as exc:
                if exc.code != APIErrorCode.ValidationError or "icon" not in kwargs:
                    raise
                kwargs.pop("icon")  # Notion does not know every emoji
                page = await self._client.pages.create(**kwargs)
        except APIResponseError as exc:
            log.warning("Zutat %r nicht angelegt: %s", name, exc.code)
            return None
        self._ingredient_ids[name] = page["id"]
        if emoji:
            self._ingredient_icons[name] = emoji
        return page["id"]

    async def _relation_ids(self, page_id: str, prop_name: str) -> list[str]:
        page = await self._client.pages.retrieve(page_id=page_id)
        prop = (page.get("properties") or {}).get(prop_name) or {}
        ids = [ref["id"] for ref in prop.get("relation") or []]
        if prop.get("has_more") and prop.get("id"):
            # Page objects list only 25 relations; the property endpoint has them all.
            items = await async_collect_paginated_api(
                self._client.pages.properties.retrieve, page_id=page_id, property_id=prop["id"]
            )
            ids = [item["relation"]["id"] for item in items if item.get("type") == "relation"]
        return ids

    def _update_cached(self, page_id: str, value: bool) -> None:
        self._replace_cached(page_id, this_week=value)

    def _replace_cached(self, page_id: str, **changes: Any) -> Recipe | None:
        if self._cache is None:
            return None
        wanted = page_id.replace("-", "")
        updated = None
        recipes = []
        for recipe in self._cache:
            if recipe.short_id == wanted:
                recipe = updated = dataclasses.replace(recipe, **changes)
            recipes.append(recipe)
        self._cache = recipes
        return updated

    # --- Cooked and rated ----------------------------------------------------------------

    @property
    def people(self) -> list[str]:
        """Who can rate: everyone with a "Bewertung <Name>" field."""
        return [person for person, _ in self._mapping.ratings] if self._mapping else []

    @property
    def supports_cooked(self) -> bool:
        return bool(self._mapping and self._mapping.last_cooked)

    async def set_rating(self, page_id: str, person: str, stars: int | None) -> Recipe | None:
        """Set or remove (None) one person's stars. Returns the updated recipe from the cache."""
        prop = dict(self._mapping.ratings).get(person) if self._mapping else None
        if prop is None:
            raise RuntimeError(f"Die Rezeptdatenbank hat kein Feld „{rating_name(self._wanted, person)}“.")
        await self._client.pages.update(page_id=page_id, properties={prop: {"number": stars}})
        return self._cache_rating(page_id, person, stars)

    async def mark_cooked(
        self, page_id: str, *, person: str, today: str, stars: int | None = None, note: str | None = None
    ) -> Recipe | None:
        """"Gekocht": sets "Zuletzt gekocht", the person's stars and appends the note."""
        if not self._mapping or not self._mapping.last_cooked:
            raise RuntimeError(f"Die Rezeptdatenbank hat kein Feld „{self._wanted.last_cooked}“.")
        m = self._mapping
        props: dict[str, Any] = {m.last_cooked: {"date": {"start": today}}}
        prop = dict(m.ratings).get(person)
        if stars and prop:
            props[prop] = {"number": stars}
        text = None
        if note and note.strip() and m.note:
            # Read the note fresh, so a line written in Notion meanwhile is kept.
            page = await self._client.pages.retrieve(page_id=page_id)
            current = _plain_text(((page.get("properties") or {}).get(m.note) or {}).get("rich_text"))
            day = f"{today[8:10]}.{today[5:7]}.{today[:4]}"
            text = append_note(current, f"{day} {person}: {' '.join(note.split())}")
            props[m.note] = {"rich_text": [_text(chunk) for chunk in _chunks(text, MAX_TEXT)]}
        await self._client.pages.update(page_id=page_id, properties=props)
        recipe = self._replace_cached(page_id, last_cooked=today, **({"note": text} if text is not None else {}))
        if stars and prop:
            recipe = self._cache_rating(page_id, person, stars) or recipe
        return recipe

    def _cache_rating(self, page_id: str, person: str, stars: int | None) -> Recipe | None:
        recipe = next((r for r in self._cache or [] if r.short_id == page_id.replace("-", "")), None)
        if recipe is None:
            return None
        order = self.people
        ratings = [(p, s) for p, s in recipe.ratings if p != person]
        if stars:
            ratings.append((person, stars))
        ratings.sort(key=lambda r: order.index(r[0]) if r[0] in order else len(order))
        return self._replace_cached(page_id, ratings=tuple(ratings))


NOTE_LIMIT = 6000  # characters kept in "Notiz"; the oldest lines go first


def append_note(current: str, line: str) -> str:
    """The note with one more line at the end, the oldest lines dropped beyond NOTE_LIMIT."""
    lines = [*(current.splitlines() if current else []), line]
    while len(lines) > 1 and len("\n".join(lines)) > NOTE_LIMIT:
        lines.pop(0)
    return "\n".join(lines)[-NOTE_LIMIT:]


def _chunks(text: str, size: int) -> list[str]:
    """Notion takes at most `size` characters per text object."""
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


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
