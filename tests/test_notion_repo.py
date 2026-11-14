"""Tests against the real notion-client with a mocked HTTP transport."""

import json

import httpx
from notion_client import AsyncClient

from koch_guru.config import PropertyNames
from koch_guru.notion_repo import PropertyMapping, RecipeRepository, page_to_recipe, resolve_mapping

DB_ID = "0123456789abcdef0123456789abcdef"
DB_UUID = "01234567-89ab-cdef-0123-456789abcdef"
DS_ID = "ds-1"

SCHEMA_OLD_CODE = {
    "Recipe": {"type": "title"},
    "Link": {"type": "url"},
    "Tags": {"type": "multi_select"},
    "Zutaten": {"type": "rich_text"},
}


def text(value):
    return [{"plain_text": part} for part in value] if isinstance(value, list) else [{"plain_text": value}]


def page(i, name, link=None, tags=(), zutaten=None):
    return {
        "object": "page",
        "id": f"page-{i}",
        "url": f"https://www.notion.so/page{i}",
        "properties": {
            "Recipe": {"type": "title", "title": text(name) if name else []},
            "Link": {"type": "url", "url": link},
            "Tags": {"type": "multi_select", "multi_select": [{"name": t} for t in tags]},
            "Zutaten": {"type": "rich_text", "rich_text": text(zutaten) if zutaten else []},
        },
    }


def test_mapping_for_schema_the_old_code_expected():
    m = resolve_mapping(SCHEMA_OLD_CODE, PropertyNames())
    assert m == PropertyMapping(title="Recipe", link="Link", tags="Tags", ingredients="Zutaten")


def test_mapping_detects_title_and_url_by_type():
    schema = {"Name": {"type": "title"}, "Rezept-Link": {"type": "url"}, "Tags": {"type": "multi_select"}}
    m = resolve_mapping(schema, PropertyNames())
    assert m == PropertyMapping(title="Name", link="Rezept-Link", tags="Tags", ingredients=None)


def test_mapping_ignores_wrong_types():
    schema = {"Titel": {"type": "title"}, "Tags": {"type": "checkbox"}, "Zutaten": {"type": "number"}}
    m = resolve_mapping(schema, PropertyNames())
    assert (m.link, m.tags, m.ingredients) == (None, None, None)


def test_page_to_recipe_joins_rich_text_and_skips_empty_rows():
    mapping = resolve_mapping(SCHEMA_OLD_CODE, PropertyNames())
    r = page_to_recipe(page(1, ["Linsen", "curry"], "https://x.de/a_b", ["Curry"], "Linsen, Kokos"), mapping)
    assert r.name == "Linsencurry"
    assert r.tags == ("Curry",)
    assert r.ingredients == ("Linsen, Kokos",)
    assert r.link == "https://x.de/a_b"
    assert page_to_recipe(page(2, ""), mapping) is None


def test_link_falls_back_to_notion_page_for_unusable_urls():
    mapping = resolve_mapping(SCHEMA_OLD_CODE, PropertyNames())
    r = page_to_recipe(page(3, "Suppe", "www.chefkoch.de/suppe"), mapping)
    assert r.link == "https://www.notion.so/page3"


class FakeNotion:
    """Minimal Notion API: one database with one data source and 250 pages."""

    def __init__(self, total=250, database_exists=True):
        self.pages = [page(i, f"Rezept {i:03d}") for i in range(total)]
        self.pages.append(page(999, ""))  # empty row, must be skipped
        self.database_exists = database_exists
        self.query_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1/databases/{DB_UUID}":
            if not self.database_exists:
                return httpx.Response(404, json={"object": "error", "status": 404,
                                                 "code": "object_not_found", "message": "nope"})
            return httpx.Response(200, json={"object": "database", "data_sources": [{"id": DS_ID, "name": "Rezepte"}]})
        if path in (f"/v1/data_sources/{DS_ID}", f"/v1/data_sources/{DB_UUID}"):
            return httpx.Response(200, json={"object": "data_source", "properties": SCHEMA_OLD_CODE})
        if path.endswith("/query"):
            self.query_calls += 1
            body = json.loads(request.content or b"{}")
            start = int(body.get("start_cursor") or 0)
            size = body.get("page_size", 100)
            chunk = self.pages[start:start + size]
            nxt = start + size
            more = nxt < len(self.pages)
            return httpx.Response(200, json={"object": "list", "results": chunk,
                                             "has_more": more, "next_cursor": str(nxt) if more else None})
        return httpx.Response(404, json={"object": "error", "status": 404, "code": "object_not_found", "message": path})


def make_repo(fake, cache_seconds=300):
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    client = AsyncClient(auth="secret", client=http)
    return RecipeRepository(client, f"https://www.notion.so/ws/Rezepte-{DB_ID}?v=1", PropertyNames(), cache_seconds)


async def test_loads_all_pages_beyond_100():
    fake = FakeNotion(total=250)
    repo = make_repo(fake)
    recipes = await repo.list_recipes()
    assert len(recipes) == 250
    assert fake.query_calls == 3
    assert recipes[0].name == "Rezept 000"


async def test_cache_and_force_refresh():
    fake = FakeNotion(total=5)
    repo = make_repo(fake)
    await repo.list_recipes()
    await repo.list_recipes()
    assert fake.query_calls == 1
    await repo.list_recipes(force_refresh=True)
    assert fake.query_calls == 2


async def test_database_id_that_is_already_a_data_source_id():
    fake = FakeNotion(total=3, database_exists=False)
    repo = make_repo(fake)
    assert len(await repo.list_recipes()) == 3
