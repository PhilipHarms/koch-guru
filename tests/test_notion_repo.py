"""Tests against the real notion-client with a mocked HTTP transport."""

import json

import httpx
from notion_client import AsyncClient

from koch_guru.config import PropertyNames
from koch_guru.notion_repo import PropertyMapping, RecipeRepository, page_to_recipe, resolve_mapping

DB_ID = "0123456789abcdef0123456789abcdef"
DB_UUID = "01234567-89ab-cdef-0123-456789abcdef"
DS_ID = "ds-1"
ING_DS = "ing-ds"

# Schema as in Philip's recipe database
SCHEMA = {
    "Name": {"type": "title"},
    "Ingredients": {"type": "relation", "relation": {"data_source_id": ING_DS, "database_id": "ing-db"}},
    "Link": {"type": "url"},
    "Origin": {"type": "multi_select"},
    "Tags": {"type": "multi_select"},
    "This Week?": {"type": "checkbox"},
}
INGREDIENTS = {"ing-1": "Gelbe Linsen", "ing-2": "Kurkuma", "ing-3": "Süßkartoffel"}


def text(value):
    return [{"plain_text": part} for part in value] if isinstance(value, list) else [{"plain_text": value}]


def page(i, name, link=None, tags=(), origin=(), ingredients=(), this_week=False):
    return {
        "object": "page",
        "id": f"page-{i}",
        "url": f"https://www.notion.so/page{i}",
        "properties": {
            "Name": {"type": "title", "title": text(name) if name else []},
            "Ingredients": {"type": "relation", "relation": [{"id": x} for x in ingredients], "has_more": False},
            "Link": {"type": "url", "url": link},
            "Origin": {"type": "multi_select", "multi_select": [{"name": o} for o in origin]},
            "Tags": {"type": "multi_select", "multi_select": [{"name": t} for t in tags]},
            "This Week?": {"type": "checkbox", "checkbox": this_week},
        },
    }


def ingredient_page(page_id, name):
    return {"object": "page", "id": page_id, "properties": {"Name": {"type": "title", "title": text(name)}}}


def test_mapping_for_philips_schema():
    m = resolve_mapping(SCHEMA, PropertyNames())
    assert (m.title, m.link, m.tags, m.origin, m.this_week) == ("Name", "Link", "Tags", "Origin", "This Week?")
    assert (m.ingredients, m.ingredients_kind) == ("Ingredients", "relation")
    assert m.ingredients_source == {"data_source_id": ING_DS, "database_id": "ing-db"}


def test_mapping_with_text_ingredients_and_fallback_url():
    schema = {"Rezept": {"type": "title"}, "Quelle-URL": {"type": "url"}, "Ingredients": {"type": "rich_text"}}
    m = resolve_mapping(schema, PropertyNames())
    assert (m.title, m.link, m.ingredients_kind, m.tags, m.this_week) == ("Rezept", "Quelle-URL", "list", None, None)


def test_mapping_ignores_wrong_types():
    schema = {"Titel": {"type": "title"}, "Tags": {"type": "checkbox"}, "This Week?": {"type": "date"}}
    m = resolve_mapping(schema, PropertyNames())
    assert (m.link, m.tags, m.ingredients, m.this_week) == (None, None, None, None)


def test_page_to_recipe_resolves_relations_and_reads_all_fields():
    mapping = resolve_mapping(SCHEMA, PropertyNames())
    p = page(1, ["Sweet Potatoes, ", "Lentils"], "https://x.de/a_b", ["Veggie", "Winter"],
             ["Green Feast (Autumn Winter)"], ["ing-1", "ing-3", "unbekannt"], this_week=True)
    r = page_to_recipe(p, mapping, INGREDIENTS)
    assert r.name == "Sweet Potatoes, Lentils"
    assert r.tags == ("Veggie", "Winter")
    assert r.origin == ("Green Feast (Autumn Winter)",)
    assert r.ingredients == ("Gelbe Linsen", "Süßkartoffel")
    assert r.this_week is True
    assert r.link == "https://x.de/a_b"
    assert r.short_id == "page1"
    assert page_to_recipe(page(2, ""), mapping) is None


def test_link_falls_back_to_notion_page_for_missing_or_unusable_urls():
    mapping = resolve_mapping(SCHEMA, PropertyNames())
    assert page_to_recipe(page(3, "Suppe", "www.chefkoch.de/suppe"), mapping).link == "https://www.notion.so/page3"
    assert page_to_recipe(page(4, "Curry"), mapping).link == "https://www.notion.so/page4"


class FakeNotion:
    """Minimal Notion API: recipe database plus a related ingredients database."""

    def __init__(self, total=250, database_exists=True, ingredients_shared=True):
        self.pages = [page(i, f"Rezept {i:03d}", ingredients=["ing-1", "ing-2"], this_week=i in (1, 2))
                      for i in range(total)]
        self.pages.append(page(999, ""))  # empty row, must be skipped
        self.database_exists = database_exists
        self.ingredients_shared = ingredients_shared
        self.query_calls = 0
        self.updates = []

    @staticmethod
    def error(status, code):
        return httpx.Response(status, json={"object": "error", "status": status, "code": code, "message": code})

    def paginate(self, items, request):
        body = json.loads(request.content or b"{}")
        start = int(body.get("start_cursor") or 0)
        size = body.get("page_size", 100)
        nxt = start + size
        more = nxt < len(items)
        return httpx.Response(200, json={"object": "list", "results": items[start:nxt],
                                         "has_more": more, "next_cursor": str(nxt) if more else None})

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"/v1/databases/{DB_UUID}":
            if not self.database_exists:
                return self.error(404, "object_not_found")
            return httpx.Response(200, json={"object": "database", "data_sources": [{"id": DS_ID, "name": "Rezepte"}]})
        if path in (f"/v1/data_sources/{DS_ID}", f"/v1/data_sources/{DB_UUID}"):
            return httpx.Response(200, json={"object": "data_source", "properties": SCHEMA})
        if path == f"/v1/data_sources/{ING_DS}/query":
            if not self.ingredients_shared:
                return self.error(404, "object_not_found")
            return self.paginate([ingredient_page(k, v) for k, v in INGREDIENTS.items()], request)
        if path.endswith("/query"):
            self.query_calls += 1
            return self.paginate(self.pages, request)
        if path.startswith("/v1/pages/") and request.method == "PATCH":
            page_id = path.rsplit("/", 1)[1]
            self.updates.append((page_id, json.loads(request.content)))
            return httpx.Response(200, json={"object": "page", "id": page_id, "properties": {}})
        return self.error(404, "object_not_found")


def make_repo(fake, cache_seconds=300):
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    client = AsyncClient(auth="secret", client=http)
    return RecipeRepository(client, f"https://www.notion.so/ws/Rezepte-{DB_ID}?v=1", PropertyNames(), cache_seconds)


async def test_loads_all_pages_beyond_100_with_ingredient_names():
    fake = FakeNotion(total=250)
    repo = make_repo(fake)
    recipes = await repo.list_recipes()
    assert len(recipes) == 250
    assert fake.query_calls == 3
    assert recipes[0].name == "Rezept 000"
    assert recipes[0].ingredients == ("Gelbe Linsen", "Kurkuma")
    assert repo.supports_this_week


async def test_without_access_to_ingredients_recipes_still_load():
    fake = FakeNotion(total=3, ingredients_shared=False)
    recipes = await make_repo(fake).list_recipes()
    assert len(recipes) == 3
    assert all(r.ingredients == () for r in recipes)


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


async def test_set_this_week_updates_checkbox_and_cache():
    fake = FakeNotion(total=5)
    repo = make_repo(fake)
    await repo.list_recipes()
    await repo.set_this_week("page4", True)
    assert fake.updates == [("page4", {"properties": {"This Week?": {"checkbox": True}}})]
    cached = {r.name: r.this_week for r in await repo.list_recipes()}
    assert cached["Rezept 004"] is True
    assert fake.query_calls == 1  # no reload needed


async def test_clear_this_week_unticks_only_planned_recipes():
    fake = FakeNotion(total=5)
    repo = make_repo(fake)
    assert await repo.clear_this_week() == 2
    assert sorted(page_id for page_id, _ in fake.updates) == ["page-1", "page-2"]
    assert all(body["properties"]["This Week?"]["checkbox"] is False for _, body in fake.updates)
