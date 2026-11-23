"""The "Kochprotokoll": one Notion page each time a recipe is cooked.

"Zuletzt gekocht" on a recipe keeps only the latest date, so every new one overwrites the
last. Stats (what how often) and a review of the year need every time, so each "Gekocht"
also adds a page to a database of its own, linked to the recipe both ways: in Notion every
recipe shows its "Kochprotokoll".

The database is found through that link, a relation of the recipe database whose target is
titled "Kochprotokoll". Without one, the app creates it next to the recipe database or, when
it may not write there, inside a page named "Kochprotokoll" shared with the integration.
Nothing here may stop the app: without a log, cooking is recorded as before.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from notion_client import AsyncClient, APIResponseError
from notion_client.helpers import async_collect_paginated_api

log = logging.getLogger(__name__)

TITLE = "Kochprotokoll"

# Field names in the log database, with their Notion type.
DISH = "Gericht"  # title
RECIPE = "Rezept"  # relation to the recipe database, both ways
DAY = "Datum"
WHO = "Wer"
STARS = "Sterne"
NOTE = "Notiz"
SOURCE = "Quelle"
FIELDS = {RECIPE: "relation", DAY: "date", WHO: "select", STARS: "number", NOTE: "rich_text", SOURCE: "select"}

# How an entry came about.
COOKING_MODE = "Kochmodus"
LATER = "Nachgetragen"  # "Gekocht?" when taking it off the week list, or clearing the list
TAKEN_OVER = "Übernommen"  # from "Zuletzt gekocht", for recipes without an entry
SOURCE_COLORS = {COOKING_MODE: "green", LATER: "blue", TAKEN_OVER: "gray"}

PACE = 0.35  # seconds between pages written in a row; Notion allows about three requests a second

NO_PLACE = (
    "Für das Kochprotokoll fehlt ein Ort: Leg in Notion eine leere Seite „Kochprotokoll“ an, "
    "verbinde sie mit der KochGuru-Integration und starte die App neu."
)


def _plain(rich: list[dict[str, Any]] | None) -> str:
    return "".join(part.get("plain_text") or (part.get("text") or {}).get("content", "") for part in rich or [])


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _short(page_id: str) -> str:
    return page_id.replace("-", "")


def _text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": {"content": content[:2000]}}


@dataclass(frozen=True)
class LogEntry:
    recipe_id: str
    day: str | None
    person: str | None
    stars: float | None
    source: str | None


class CookLog:
    """Finds or creates the log database and writes its pages."""

    def __init__(self, client: AsyncClient, people: list[str] | tuple[str, ...] = ()) -> None:
        self._client = client
        self._people = tuple(people)
        self.data_source_id: str | None = None
        self.url: str | None = None
        self.problem: str | None = None  # why there is no log, shown in the app's data
        self._fields: dict[str, str] = {}  # our name -> name in Notion
        self._title: str | None = None

    @property
    def ready(self) -> bool:
        return self.data_source_id is not None

    def status(self) -> dict[str, Any]:
        return {"ready": self.ready, "url": self.url, "problem": self.problem}

    # --- Finding or creating the database ---------------------------------------------------

    async def connect(
        self,
        *,
        recipe_source_id: str,
        recipe_database_id: str | None,
        recipe_schema: dict[str, dict[str, Any]],
        skip_sources: set[str] = frozenset(),  # type: ignore[assignment]
    ) -> None:
        try:
            if await self._find(recipe_schema, skip_sources):
                return
            await self._create(recipe_source_id, recipe_database_id, recipe_schema)
        except APIResponseError as exc:
            self.problem = f"Das Kochprotokoll ist nicht erreichbar ({exc.code})."
            log.warning("Kochprotokoll: %s", exc)

    async def _find(self, recipe_schema: dict[str, dict[str, Any]], skip: set[str]) -> bool:
        """The log behind a relation of the recipe database, found by its title."""
        for prop in recipe_schema.values():
            if prop.get("type") != "relation":
                continue
            target = (prop.get("relation") or {}).get("data_source_id")
            if not target or target in skip:
                continue
            try:
                source = await self._client.data_sources.retrieve(data_source_id=target)
            except APIResponseError:
                continue  # another database the integration may not see
            if _same(_plain(source.get("title")) or source.get("name") or "", TITLE):
                return self._use(source)
        return False

    async def _create(
        self, recipe_source_id: str, recipe_database_id: str | None, recipe_schema: dict[str, dict[str, Any]]
    ) -> None:
        for parent in await self._places(recipe_database_id):
            try:
                database = await self._client.databases.create(
                    parent={"type": "page_id", "page_id": parent},
                    title=[_text(TITLE)],
                    icon={"type": "emoji", "emoji": "📓"},
                    initial_data_source={"properties": self._schema(recipe_source_id)},
                )
            except APIResponseError as exc:
                log.info("Kochprotokoll nicht in %s angelegt: %s", parent, exc.code)
                continue
            sources = database.get("data_sources") or []
            if not sources:
                continue
            source = await self._client.data_sources.retrieve(data_source_id=sources[0]["id"])
            if self._use(source):
                self.url = database.get("url") or self.url
                log.info("Kochprotokoll angelegt: %s", self.url)
                await self._name_backlink(recipe_source_id, recipe_schema, source)
                return
        self.problem = NO_PLACE
        log.warning(NO_PLACE)

    async def _places(self, recipe_database_id: str | None) -> list[str]:
        """Pages to create the log in: next to the recipe database, then a page named "Kochprotokoll"."""
        places: list[str] = []
        if recipe_database_id:
            try:
                database = await self._client.databases.retrieve(database_id=recipe_database_id)
                parent = database.get("parent") or {}
                if parent.get("type") == "page_id":
                    places.append(parent["page_id"])
            except APIResponseError:
                pass
        try:
            found = await self._client.search(query=TITLE, filter={"property": "object", "value": "page"})
        except APIResponseError:
            found = {}
        for result in found.get("results") or []:
            title = next(
                (_plain(p.get("title")) for p in (result.get("properties") or {}).values() if p.get("type") == "title"),
                "",
            )
            if _same(title, TITLE) and result.get("id") not in places:
                places.append(result["id"])
        return places

    def _schema(self, recipe_source_id: str) -> dict[str, Any]:
        return {
            DISH: {"title": {}},
            RECIPE: {"relation": {"data_source_id": recipe_source_id, "type": "dual_property", "dual_property": {}}},
            DAY: {"date": {}},
            WHO: {"select": {"options": [{"name": person} for person in self._people]}},
            STARS: {"number": {"format": "number"}},
            NOTE: {"rich_text": {}},
            SOURCE: {"select": {"options": [{"name": n, "color": c} for n, c in SOURCE_COLORS.items()]}},
        }

    async def _name_backlink(
        self, recipe_source_id: str, recipe_schema: dict[str, dict[str, Any]], source: dict[str, Any]
    ) -> None:
        """Notion names the new field in the recipe database itself; call it "Kochprotokoll"."""
        if any(_same(name, TITLE) for name in recipe_schema):
            return
        relation = ((source.get("properties") or {}).get(self._fields[RECIPE]) or {}).get("relation") or {}
        synced = (relation.get("dual_property") or {}).get("synced_property_id")
        if not synced:
            return
        try:
            await self._client.data_sources.update(
                data_source_id=recipe_source_id, properties={synced: {"name": TITLE}}
            )
        except APIResponseError as exc:
            log.info("Feld „%s“ in der Rezeptdatenbank nicht umbenannt: %s", TITLE, exc.code)

    def _use(self, source: dict[str, Any]) -> bool:
        """Take this database if it has a title, a link to the recipe and a date; the rest is optional."""
        props = source.get("properties") or {}
        fields = {}
        for wanted, kind in FIELDS.items():
            name = next((n for n, p in props.items() if _same(n, wanted) and p.get("type") == kind), None)
            if name:
                fields[wanted] = name
        title = next((n for n, p in props.items() if p.get("type") == "title"), None)
        if not title or RECIPE not in fields or DAY not in fields:
            self.problem = f"Die Datenbank „{TITLE}“ braucht die Felder „{RECIPE}“ (Verknüpfung) und „{DAY}“."
            log.warning(self.problem)
            return True  # found, but unusable: do not create a second one
        self.data_source_id = source["id"]
        self.url = source.get("url") or self.url
        self._fields, self._title, self.problem = fields, title, None
        log.info("Kochprotokoll verbunden")
        return True

    # --- Entries ----------------------------------------------------------------------------

    async def add(
        self,
        *,
        recipe_id: str,
        name: str,
        day: str,
        person: str | None = None,
        stars: float | None = None,
        note: str | None = None,
        source: str = COOKING_MODE,
    ) -> None:
        if not self.ready:
            return
        f = self._fields
        props: dict[str, Any] = {
            self._title: {"title": [_text(name)]},
            f[RECIPE]: {"relation": [{"id": recipe_id}]},
            f[DAY]: {"date": {"start": day}},
        }
        if person and WHO in f:
            props[f[WHO]] = {"select": {"name": person}}
        if stars and STARS in f:
            props[f[STARS]] = {"number": stars}
        if note and note.strip() and NOTE in f:
            props[f[NOTE]] = {"rich_text": [_text(" ".join(note.split()))]}
        if SOURCE in f:
            props[f[SOURCE]] = {"select": {"name": source}}
        await self._client.pages.create(parent={"type": "data_source_id", "data_source_id": self.data_source_id},
                                        properties=props)

    async def entries(self) -> list[LogEntry]:
        if not self.ready:
            return []
        pages = await async_collect_paginated_api(
            self._client.data_sources.query, data_source_id=self.data_source_id, page_size=100
        )
        f = self._fields
        found = []
        for page in pages:
            props = page.get("properties") or {}
            for link in (props.get(f[RECIPE]) or {}).get("relation") or []:
                who = (props.get(f.get(WHO, "")) or {}).get("select") or {}
                origin = (props.get(f.get(SOURCE, "")) or {}).get("select") or {}
                found.append(LogEntry(
                    recipe_id=link["id"],
                    day=((props.get(f[DAY]) or {}).get("date") or {}).get("start"),
                    person=who.get("name"),
                    stars=(props.get(f.get(STARS, "")) or {}).get("number"),
                    source=origin.get("name"),
                ))
        return found

    async def take_over(self, recipes: list[Any]) -> int:
        """An entry from "Zuletzt gekocht" for each recipe the log knows nothing about yet.

        Runs at every start, so dates set in Notion by hand arrive too. A recipe with any
        entry is left alone, so deleting one of several entries in Notion sticks.
        """
        if not self.ready:
            return 0
        known = {_short(e.recipe_id) for e in await self.entries()}
        added = 0
        for recipe in recipes:
            if not recipe.last_cooked or recipe.short_id in known:
                continue
            await self.add(recipe_id=recipe.id, name=recipe.name, day=recipe.last_cooked, source=TAKEN_OVER)
            added += 1
            await asyncio.sleep(PACE)
        if added:
            log.info("Kochprotokoll: %d Einträge aus „Zuletzt gekocht“ übernommen", added)
        return added
