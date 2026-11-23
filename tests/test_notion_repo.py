"""Tests against the real notion-client with a mocked HTTP transport."""

import json

import httpx
from notion_client import AsyncClient

from koch_guru.config import PropertyNames
from koch_guru.notion_repo import RecipeRepository, draft_blocks, page_icon, page_to_recipe, resolve_mapping
from koch_guru.services.importer import RecipeDraft

DB_ID = "0123456789abcdef0123456789abcdef"
DB_UUID = "01234567-89ab-cdef-0123-456789abcdef"
DS_ID = "ds-1"
ING_DS = "ing-ds"

# Schema as in Philip's recipe database
SCHEMA = {
    "Name": {"type": "title"},
    "Ingredients": {"type": "relation", "relation": {"data_source_id": ING_DS, "database_id": "ing-db"}},
    "Link": {"type": "url"},
    "Origin": {"type": "multi_select", "multi_select": {"options": [{"name": "Green Feast (Autumn Winter)"}]}},
    "Tags": {"type": "multi_select", "multi_select": {"options": [{"name": "Veggie"}, {"name": "Winter"}]}},
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


def ingredient_page(page_id, name, bought=False):
    return {"object": "page", "id": page_id, "icon": {"type": "emoji", "emoji": f"E{page_id[-1]}"},
            "properties": {"Name": {"type": "title", "title": text(name)},
                           "Bought": {"type": "checkbox", "checkbox": bought}}}


# Schema of Philip's ingredients database before the app added its fields
INGREDIENT_SCHEMA = {"Name": {"type": "title"}, "Bought": {"type": "checkbox"},
                     "Rezepte": {"type": "relation", "relation": {"data_source_id": DS_ID}}}


def test_mapping_for_philips_schema():
    m = resolve_mapping(SCHEMA, PropertyNames())
    assert (m.title, m.link, m.tags, m.origin, m.this_week) == ("Name", "Link", "Tags", "Origin", "This Week?")
    assert (m.ingredients, m.ingredients_kind) == ("Ingredients", "relation")
    assert m.ingredients_source == {"data_source_id": ING_DS, "database_id": "ing-db"}
    assert (m.tags_type, m.tag_options) == ("multi_select", ("Veggie", "Winter"))


def test_mapping_with_text_ingredients_and_fallback_url():
    schema = {"Rezept": {"type": "title"}, "Quelle-URL": {"type": "url"}, "Ingredients": {"type": "rich_text"}}
    m = resolve_mapping(schema, PropertyNames())
    assert (m.title, m.link, m.ingredients_kind, m.tags, m.this_week) == ("Rezept", "Quelle-URL", "list", None, None)


def test_mapping_ignores_wrong_types():
    schema = {"Titel": {"type": "title"}, "Tags": {"type": "checkbox"}, "This Week?": {"type": "date"}}
    m = resolve_mapping(schema, PropertyNames())
    assert (m.link, m.tags, m.ingredients, m.this_week) == (None, None, None, None)


def test_page_emoji_icon_becomes_recipe_emoji():
    mapping = resolve_mapping(SCHEMA, PropertyNames())
    with_emoji = page(5, "Dal") | {"icon": {"type": "emoji", "emoji": "🍛"}}
    with_file = page(6, "Salat") | {"icon": {"type": "external", "external": {"url": "https://x/icon.png"}}}
    assert page_to_recipe(with_emoji, mapping).emoji == "🍛"
    assert page_to_recipe(with_file, mapping).emoji is None
    assert page_to_recipe(page(7, "Suppe"), mapping).emoji is None


def test_created_time_is_kept_for_sorting():
    mapping = resolve_mapping(SCHEMA, PropertyNames())
    created = page(8, "Dal") | {"created_time": "2026-11-01T10:00:00.000Z"}
    assert page_to_recipe(created, mapping).created == "2026-11-01T10:00:00.000Z"


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
        self.created = []
        self.reject_icons = False
        self.reject_uploads = False
        self.uploads = []
        self.sent = []
        self.blocks = {}
        self.block_calls = []
        self.appended = []
        self.appended_after = []
        self.deleted = []
        self.reject_ingredients = False
        self.ingredient_schema = dict(INGREDIENT_SCHEMA)
        self.schema_updates = []
        self.recipe_schema = dict(SCHEMA)
        self.recipe_schema_updates = []
        self.reject_schema_updates = False
        self.bought = {"ing-2"}
        self.ingredient_tags = {}

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
        if path == f"/v1/data_sources/{ING_DS}" and request.method == "GET":
            return httpx.Response(200, json={"object": "data_source", "properties": self.ingredient_schema})
        if path == f"/v1/data_sources/{ING_DS}" and request.method == "PATCH":
            if self.reject_schema_updates:
                return self.error(403, "restricted_resource")
            body = json.loads(request.content)
            self.schema_updates.append(body)
            for name, prop in body["properties"].items():
                self.ingredient_schema[name] = {"type": next(iter(prop))}
            return httpx.Response(200, json={"object": "data_source", "properties": self.ingredient_schema})
        if path in (f"/v1/data_sources/{DS_ID}", f"/v1/data_sources/{DB_UUID}"):
            if request.method == "PATCH":
                body = json.loads(request.content)
                self.recipe_schema_updates.append(body)
                for name, prop in body["properties"].items():
                    self.recipe_schema[name] = {"type": next(iter(prop))}
            return httpx.Response(200, json={"object": "data_source", "properties": self.recipe_schema})
        if path == f"/v1/data_sources/{ING_DS}/query":
            if not self.ingredients_shared:
                return self.error(404, "object_not_found")
            pages = [ingredient_page(k, v, k in self.bought) for k, v in INGREDIENTS.items()]
            for p in pages:
                if p["id"] in self.ingredient_tags:
                    p["properties"]["Tags"] = {"type": "multi_select",
                                               "multi_select": [{"name": t} for t in self.ingredient_tags[p["id"]]]}
            return self.paginate(pages, request)
        if path.startswith("/v1/blocks/") and path.endswith("/children") and request.method == "GET":
            block_id = path.split("/")[3]
            self.block_calls.append(block_id)
            return self.paginate(self.blocks.get(block_id, []), request)
        if path.endswith("/query"):
            self.query_calls += 1
            return self.paginate(self.pages, request)
        if path == "/v1/file_uploads" and request.method == "POST":
            if self.reject_uploads:
                return self.error(403, "restricted_resource")
            body = json.loads(request.content)
            self.uploads.append(body)
            return httpx.Response(200, json={"object": "file_upload", "id": f"fu-{len(self.uploads)}",
                                             "status": "pending"})
        if path.startswith("/v1/file_uploads/") and path.endswith("/send"):
            self.sent.append((path.split("/")[3], request.headers["content-type"], request.content))
            return httpx.Response(200, json={"object": "file_upload", "id": path.split("/")[3], "status": "uploaded"})
        if path == "/v1/pages" and request.method == "POST":
            body = json.loads(request.content)
            self.created.append(body)
            if self.reject_icons and "icon" in body:
                return self.error(400, "validation_error")
            if (body.get("parent") or {}).get("data_source_id") == ING_DS:
                if self.reject_ingredients:
                    return self.error(403, "restricted_resource")
                return httpx.Response(200, json={"object": "page", "id": f"ing-new-{len(self.created)}"})
            return httpx.Response(200, json=page(500, "Neues Rezept", "https://example.com/r"))
        if path.startswith("/v1/blocks/") and path.endswith("/children") and request.method == "PATCH":
            body = json.loads(request.content)
            self.appended.append((path.split("/")[3], body["children"]))
            self.appended_after.append(body.get("after"))
            return httpx.Response(200, json={"object": "list", "results": [], "has_more": False, "next_cursor": None})
        if path.startswith("/v1/blocks/") and request.method == "DELETE":
            self.deleted.append(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"object": "block", "id": path.rsplit("/", 1)[1], "in_trash": True})
        if path.startswith("/v1/pages/") and request.method == "GET":
            page_id = path.rsplit("/", 1)[1]
            found = next((p for p in self.pages if p["id"] == page_id), None)
            return httpx.Response(200, json=found) if found else self.error(404, "object_not_found")
        if path.startswith("/v1/pages/") and request.method == "PATCH":
            page_id = path.rsplit("/", 1)[1]
            body = json.loads(request.content)
            self.updates.append((page_id, body))
            # Like Notion: the updated page; here only with the fields that were sent.
            answer = {"object": "page", "id": page_id, "properties": {
                name: {"type": next(iter(value)), **value} for name, value in (body.get("properties") or {}).items()}}
            if "icon" in body:
                answer["icon"] = body["icon"]
            if (body.get("cover") or {}).get("type") == "file_upload":
                upload = body["cover"]["file_upload"]["id"]
                answer["cover"] = {"type": "file", "file": {"url": f"https://files.notion.so/{upload}.jpg?X-Amz-Signature=1"}}
            return httpx.Response(200, json=answer)
        return self.error(404, "object_not_found")


def make_repo(fake, cache_seconds=300, people=()):
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    client = AsyncClient(auth="secret", client=http)
    return RecipeRepository(
        client, f"https://www.notion.so/ws/Rezepte-{DB_ID}?v=1", PropertyNames(), cache_seconds, people=people
    )


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


DRAFT = RecipeDraft(
    name="Ofen-Süßkartoffeln", url="https://example.com/r", ingredients=["500 g Süßkartoffeln", "200 g Feta"],
    steps=["Backen."], servings="4", total_minutes=45, image="https://img.example/a.jpg", tags=["Veggie"],
    icon="🍠",
)


async def test_create_recipe_payload():
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    await repo.list_recipes()
    recipe = await repo.create_recipe(DRAFT)

    body = fake.created[0]
    assert body["parent"] == {"type": "data_source_id", "data_source_id": DS_ID}
    assert body["properties"]["Name"]["title"][0]["text"]["content"] == "Ofen-Süßkartoffeln"
    assert body["properties"]["Link"] == {"url": "https://example.com/r"}
    assert body["properties"]["Tags"] == {"multi_select": [{"name": "Veggie"}]}
    assert "This Week?" not in body["properties"] and "Ingredients" not in body["properties"]
    assert body["cover"] == {"type": "external", "external": {"url": "https://img.example/a.jpg"}}
    assert body["icon"] == {"type": "emoji", "emoji": "🍠"}
    kinds = [b["type"] for b in body["children"]]
    assert kinds == ["paragraph", "heading_2", "bulleted_list_item", "bulleted_list_item",
                     "heading_2", "numbered_list_item"]
    info = body["children"][0]["paragraph"]["rich_text"]
    assert info[0]["text"]["content"] == "⏱ 45 Min · 🍽 4 · Quelle: "
    assert info[1]["text"] == {"content": "example.com", "link": {"url": "https://example.com/r"}}

    assert recipe.name == "Neues Rezept"
    await repo.list_recipes()
    assert fake.query_calls == 2  # cache invalidated after creating


def test_draft_blocks_respect_notion_limits():
    long = RecipeDraft(name="X", url="https://x.de", ingredients=[f"Zutat {i}" for i in range(80)],
                       steps=["s" * 5000] * 40)
    blocks = draft_blocks(long)
    assert len(blocks) == 100
    assert "Gekürzt" in blocks[-1]["paragraph"]["rich_text"][0]["text"]["content"]
    step = next(b for b in blocks if b["type"] == "numbered_list_item")
    assert len(step["numbered_list_item"]["rich_text"][0]["text"]["content"]) == 2000


async def test_find_existing_by_link_then_by_name():
    fake = FakeNotion(total=3)
    fake.pages[1]["properties"]["Link"]["url"] = "https://www.example.com/r/"
    repo = make_repo(fake)
    existing, reason = await repo.find_existing(DRAFT)
    assert (existing.name, reason) == ("Rezept 001", "link")

    same_name = RecipeDraft(name="rezept 002", url="https://other.de/x", ingredients=["a"])
    existing, reason = await repo.find_existing(same_name)
    assert (existing.name, reason) == ("Rezept 002", "name")

    assert await repo.find_existing(RecipeDraft(name="Neu", url="https://n.de", ingredients=["a"])) == (None, "")


async def test_unknown_emoji_is_dropped_and_recipe_still_saved():
    fake = FakeNotion(total=1)
    fake.reject_icons = True
    recipe = await make_repo(fake).create_recipe(DRAFT)
    assert recipe.name == "Neues Rezept"
    assert ["icon" in body for body in fake.created] == [True, False]


PHOTO_DRAFT = RecipeDraft(
    name="Kürbis-Dal", ingredients=["1 Kürbis"], steps=["Kochen."], tags=["Veggie"], icon="🍛",
    origin=["Green Feast (Autumn Winter)"], photos=[(b"jpeg-bytes", "image/jpeg"), (b"png-bytes", "image/png")],
    source="photo",
)


async def test_create_recipe_from_photo_uploads_originals():
    fake = FakeNotion(total=1)
    await make_repo(fake).create_recipe(PHOTO_DRAFT)

    assert [u["filename"] for u in fake.uploads] == ["rezept-1.jpg", "rezept-2.png"]
    assert all(u["mode"] == "single_part" for u in fake.uploads)
    assert [s[0] for s in fake.sent] == ["fu-1", "fu-2"]
    assert fake.sent[0][1].startswith("multipart/form-data") and b"jpeg-bytes" in fake.sent[0][2]

    body = fake.created[0]
    assert "Link" not in body["properties"]
    assert body["properties"]["Origin"] == {"multi_select": [{"name": "Green Feast (Autumn Winter)"}]}
    assert "cover" not in body
    info = body["children"][0]["paragraph"]["rich_text"]
    assert [t["text"]["content"] for t in info] == ["Quelle: Green Feast (Autumn Winter)"]
    assert [b["type"] for b in body["children"][-3:]] == ["heading_2", "image", "image"]
    assert body["children"][-1]["image"] == {"type": "file_upload", "file_upload": {"id": "fu-2"}}


async def test_failed_photo_upload_still_saves_recipe():
    fake = FakeNotion(total=1)
    fake.reject_uploads = True
    await make_repo(fake).create_recipe(PHOTO_DRAFT)
    assert fake.created and all(b["type"] != "image" for b in fake.created[0]["children"])


def test_photos_keep_their_place_when_content_is_long():
    long = RecipeDraft(name="X", ingredients=[f"Zutat {i}" for i in range(120)], source="photo")
    blocks = draft_blocks(long, ["fu-1", "fu-2"])
    assert len(blocks) == 100
    assert [b["type"] for b in blocks[-4:]] == ["paragraph", "heading_2", "image", "image"]
    assert "auf dem Foto" in blocks[-4]["paragraph"]["rich_text"][0]["text"]["content"]


async def test_find_existing_without_url_matches_by_name_only():
    fake = FakeNotion(total=3)
    repo = make_repo(fake)
    assert (await repo.find_existing(RecipeDraft(name="Rezept 001", ingredients=["a"])))[1] == "name"
    assert await repo.find_existing(RecipeDraft(name="Neu", ingredients=["a"])) == (None, "")
    assert repo.origin_options == ["Green Feast (Autumn Winter)"]


def test_cover_is_read_from_external_and_notion_files():
    mapping = resolve_mapping(SCHEMA, PropertyNames())
    external = {**page(1, "A"), "cover": {"type": "external", "external": {"url": "https://img.example/a.jpg"}}}
    hosted = {**page(2, "B"), "cover": {"type": "file", "file": {"url": "https://s3.example/b.jpg?X-Amz-1"}}}
    assert page_to_recipe(external, mapping).cover == "https://img.example/a.jpg"
    assert page_to_recipe(hosted, mapping).cover == "https://s3.example/b.jpg?X-Amz-1"
    assert page_to_recipe(page(3, "C"), mapping).cover is None


async def test_ingredient_emojis_come_from_the_ingredient_pages():
    repo = make_repo(FakeNotion(total=1))
    await repo.list_recipes()
    assert repo.ingredient_icons == {"Gelbe Linsen": "E1", "Kurkuma": "E2", "Süßkartoffel": "E3"}


async def test_page_blocks_follow_nested_items_and_are_cached():
    fake = FakeNotion(total=1)
    fake.blocks = {
        "page-1": [
            {"object": "block", "id": "b1", "type": "bulleted_list_item", "has_children": True,
             "bulleted_list_item": {"rich_text": text("Tomaten")}},
            {"object": "block", "id": "b2", "type": "child_page", "has_children": True, "child_page": {}},
        ],
        "b1": [{"object": "block", "id": "b3", "type": "bulleted_list_item", "has_children": False,
                "bulleted_list_item": {"rich_text": text("Kirschtomaten")}}],
    }
    repo = make_repo(fake)
    blocks = await repo.page_blocks("page-1")
    assert blocks[0]["children"][0]["id"] == "b3"
    assert "children" not in blocks[1]  # sub-pages are not opened
    await repo.page_blocks("page-1")
    assert fake.block_calls == ["page-1", "b1"]


def test_page_icon_kinds():
    assert page_icon({"icon": {"type": "emoji", "emoji": "🥚"}}) == "🥚"
    native = {"icon": {"type": "icon", "icon": {"name": "grain", "color": "brown"}}}
    assert page_icon(native) == "https://www.notion.so/icons/grain_brown.svg"
    custom = {"icon": {"type": "custom_emoji", "custom_emoji": {"id": "1", "name": "x", "url": "https://s3.example/x.png"}}}
    assert page_icon(custom) == "https://s3.example/x.png"
    assert page_icon({"icon": None}) is None


async def test_save_generated_appends_content_and_adds_links():
    fake = FakeNotion(total=3)
    fake.pages[1] = page(1, "Rezept 001", ingredients=["ing-2"])
    repo = make_repo(fake)
    await repo.list_recipes()
    draft = RecipeDraft(name="Rezept 001", url="https://example.com/r", ingredients=["2 EL Kurkuma", "200 g Pak Choi"],
                        steps=["Kochen."], servings="2 Portionen", total_minutes=20)
    not_created = await repo.save_generated(
        "page-1", draft=draft, link=[("Kurkuma", "🫙"), ("gelbe linsen", None), ("Pak Choi", "🥬")],
        cover="https://example.com/r.jpg",
    )
    assert ("page-1", {"cover": {"type": "external", "external": {"url": "https://example.com/r.jpg"}}}) in fake.updates
    assert not_created == []
    (block_id, children), = fake.appended
    assert block_id == "page-1"
    texts = [c[c["type"]]["rich_text"][0]["text"]["content"] for c in children if c[c["type"]].get("rich_text")]
    assert "Zutaten" in texts and "Zubereitung" in texts and "2 EL Kurkuma" in texts
    created = [b for b in fake.created if b["parent"].get("data_source_id") == ING_DS]
    assert [b["properties"]["Name"]["title"][0]["text"]["content"] for b in created] == ["Pak Choi"]
    assert created[0]["icon"] == {"type": "emoji", "emoji": "🥬"}
    page_id, update = fake.updates[-1]
    assert page_id == "page-1"
    assert update["properties"]["Ingredients"]["relation"] == [{"id": "ing-2"}, {"id": "ing-1"}, {"id": "ing-new-1"}]
    assert "Pak Choi" in repo.ingredient_names


async def test_save_generated_without_edit_access_to_ingredients():
    fake = FakeNotion(total=2)
    fake.reject_ingredients = True
    repo = make_repo(fake)
    await repo.list_recipes()
    draft = RecipeDraft(name="Rezept 000", ingredients=["200 g Pak Choi"], steps=[])
    assert await repo.save_generated("page-0", draft=draft, link=[("Pak Choi", "🥬")]) == ["Pak Choi"]
    assert len(fake.appended) == 1
    assert not [u for u in fake.updates if "Ingredients" in u[1].get("properties", {})]


async def test_save_generated_reports_links_it_could_not_set():
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    await repo.list_recipes()
    original = fake.handler

    def no_page_updates(request):
        if request.method == "PATCH" and request.url.path.startswith("/v1/pages/"):
            return fake.error(403, "restricted_resource")
        return original(request)

    fake.handler = no_page_updates
    repo = make_repo(fake)
    await repo.list_recipes()
    draft = RecipeDraft(name="Rezept 000", ingredients=["1 Süßkartoffel"], steps=["Kochen."])
    assert await repo.save_generated("page-0", draft=draft, link=[("Süßkartoffel", None)]) == ["Süßkartoffel"]
    assert len(fake.appended) == 1


async def test_shopping_fields_are_created_once_and_ingredients_carry_their_state():
    fake = FakeNotion(total=3)
    repo = make_repo(fake)
    recipes = await repo.list_recipes()
    assert fake.schema_updates == [{"properties": {"Gekauft am": {"date": {}}, "Extra": {"checkbox": {}}}}]
    assert (repo.ingredient_fields.bought, repo.ingredient_fields.bought_on, repo.ingredient_fields.extra) == (
        "Bought", "Gekauft am", "Extra")
    assert recipes[0].ingredient_ids == ("ing-1", "ing-2")
    assert [(i.name, i.bought, i.icon) for i in repo.ingredients.values()] == [
        ("Gelbe Linsen", False, "E1"), ("Kurkuma", True, "E2"), ("Süßkartoffel", False, "E3")]
    await repo.list_recipes(force_refresh=True)
    assert len(fake.schema_updates) == 1  # checked once per start


async def test_existing_fields_are_found_in_any_letter_case():
    fake = FakeNotion(total=1)
    fake.ingredient_schema |= {"gekauft am": {"type": "date"}, "EXTRA": {"type": "checkbox"}}
    repo = make_repo(fake)
    await repo.list_recipes()
    assert fake.schema_updates == []
    assert (repo.ingredient_fields.bought_on, repo.ingredient_fields.extra) == ("gekauft am", "EXTRA")


async def test_without_schema_access_the_list_still_loads():
    fake = FakeNotion(total=1)
    fake.reject_schema_updates = True
    repo = make_repo(fake)
    assert len(await repo.list_recipes()) == 1
    assert repo.ingredient_fields.bought == "Bought"
    assert repo.ingredient_fields.bought_on is None and repo.ingredient_fields.extra is None


async def test_set_bought_ticks_and_unticks_with_date():
    fake = FakeNotion(total=1)
    repo = make_repo(fake)
    await repo.list_recipes()
    ticked = await repo.set_bought("ing-1", True, today="2026-11-18")
    assert (ticked.bought, ticked.bought_on) == (True, "2026-11-18")
    assert fake.updates[-1] == ("ing-1", {"properties": {
        "Bought": {"checkbox": True}, "Gekauft am": {"date": {"start": "2026-11-18"}}}})
    back = await repo.set_bought("ing-1", False, today="2026-11-18")
    assert (back.bought, back.bought_on) == (False, None)
    assert fake.updates[-1][1]["properties"]["Gekauft am"] == {"date": None}
    assert repo.ingredients["ing-1"].bought is False


async def test_add_extra_creates_or_reuses_an_ingredient():
    fake = FakeNotion(total=1)
    repo = make_repo(fake)
    await repo.list_recipes()
    new = await repo.add_extra("Spülmittel")
    created = fake.created[-1]
    assert created["parent"] == {"type": "data_source_id", "data_source_id": ING_DS}
    assert created["properties"]["Name"]["title"][0]["text"]["content"] == "Spülmittel"
    assert created["properties"]["Extra"] == {"checkbox": True}
    assert (new.name, new.extra, repo.ingredients[new.id].extra) == ("Spülmittel", True, True)

    again = await repo.add_extra("kurkuma")  # bought already: back on the list
    assert again.id == "ing-2" and again.extra and not again.bought
    assert fake.updates[-1] == ("ing-2", {"properties": {
        "Extra": {"checkbox": True}, "Bought": {"checkbox": False}, "Gekauft am": {"date": None}}})


async def test_bought_with_question_mark_is_found():
    """Philip's ingredients database calls the checkbox "Bought?"."""
    fake = FakeNotion(total=1)
    fake.ingredient_schema = {"Name": {"type": "title"}, "Bought?": {"type": "checkbox"}, "Shop?": {"type": "rollup"}}
    repo = make_repo(fake)
    await repo.list_recipes()
    assert repo.ingredient_fields.bought == "Bought?"
    await repo.set_bought("ing-1", True, today="2026-11-19")
    assert fake.updates[-1][1]["properties"]["Bought?"] == {"checkbox": True}


async def test_save_generated_replaces_an_earlier_version():
    """Generate again after a wrong link: new content in place of the old, wrong links removed."""
    fake = FakeNotion(total=3)
    fake.pages[1] = page(1, "Rezept 001", ingredients=["ing-1", "ing-2"])
    repo = make_repo(fake)
    await repo.list_recipes()
    draft = RecipeDraft(name="Rezept 001", url="https://example.com/richtig", ingredients=["2 EL Kurkuma"],
                        steps=["Kochen."])
    await repo.save_generated(
        "page-1", draft=draft, link=[("Kurkuma", None)], replace_ids=["old-info", "old-zutaten", "old-1"],
        unlink_ids=["ing1"], new_link="https://example.com/richtig",
    )
    assert fake.updates[0] == ("page-1", {"properties": {"Link": {"url": "https://example.com/richtig"}}})
    assert fake.appended_after == ["old-info"]  # the new content goes where the old one started
    assert fake.deleted == ["old-info", "old-zutaten", "old-1"]
    assert fake.updates[-1][1]["properties"]["Ingredients"]["relation"] == [{"id": "ing-2"}]


async def test_save_generated_only_unlinks():
    fake = FakeNotion(total=3)
    fake.pages[1] = page(1, "Rezept 001", ingredients=["ing-1", "ing-2"])
    repo = make_repo(fake)
    await repo.list_recipes()
    draft = RecipeDraft(name="Rezept 001", url="", ingredients=["Wasser"], steps=["Kochen."])
    await repo.save_generated("page-1", draft=draft, link=[], unlink_ids=["ing-2"])
    assert fake.appended_after == [None] and fake.deleted == []
    assert fake.updates[-1][1]["properties"]["Ingredients"]["relation"] == [{"id": "ing-1"}]


async def test_aisles_come_from_the_ingredient_tags_in_notion_order():
    fake = FakeNotion(total=1)
    fake.ingredient_schema["Tags"] = {"type": "multi_select", "multi_select": {"options": [
        {"name": "Obst & Gemüse"}, {"name": "Gewürze"}, {"name": "Milchprodukt"}]}}
    fake.ingredient_tags = {"ing-1": ["Milchprodukt", "Gewürze"], "ing-3": ["Obst & Gemüse"]}
    repo = make_repo(fake)
    await repo.list_recipes()
    assert repo.ingredient_fields.aisles == ("Obst & Gemüse", "Gewürze", "Milchprodukt")
    # Two tags: the one that comes first in Notion counts.
    assert {i.name: i.aisle for i in repo.ingredients.values()} == {
        "Gelbe Linsen": "Gewürze", "Kurkuma": None, "Süßkartoffel": "Obst & Gemüse"}


async def test_new_ingredient_gets_its_aisle_tag():
    fake = FakeNotion(total=3)
    fake.ingredient_schema["Tags"] = {"type": "multi_select", "multi_select": {"options": [{"name": "Gemüse"}]}}
    fake.pages[1] = page(1, "Rezept 001", ingredients=[])
    repo = make_repo(fake)
    await repo.list_recipes()
    await repo.link_ingredients("page-1", [("Pak Choi", "🥬", "Gemüse"), ("Tofu", None, "Gibt es nicht")])
    created = {b["properties"]["Name"]["title"][0]["text"]["content"]: b["properties"]
               for b in fake.created if b["parent"].get("data_source_id") == ING_DS}
    assert created["Pak Choi"]["Tags"] == {"multi_select": [{"name": "Gemüse"}]}
    assert "Tags" not in created["Tofu"]  # no new tags from the model


async def test_cooking_fields_are_created_and_read():
    fake = FakeNotion(total=1)
    repo = make_repo(fake, people=["Philip", "Charlotte"])
    await repo.list_recipes()
    assert fake.recipe_schema_updates == [{"properties": {
        "Zuletzt gekocht": {"date": {}}, "Notiz": {"rich_text": {}},
        "Bewertung Philip": {"number": {"format": "number"}}, "Bewertung Charlotte": {"number": {"format": "number"}},
    }}]
    assert repo.people == ["Philip", "Charlotte"] and repo.supports_cooked


async def test_mark_cooked_sets_date_stars_and_appends_the_note():
    fake = FakeNotion(total=1)
    fake.recipe_schema |= {"Zuletzt gekocht": {"type": "date"}, "Notiz": {"type": "rich_text"},
                           "bewertung philip": {"type": "number"}, "Bewertung Charlotte": {"type": "number"}}
    fake.pages[0]["properties"]["Notiz"] = {"type": "rich_text", "rich_text": text("01.11.2026 Charlotte: lecker")}
    repo = make_repo(fake, people=["Philip", "Charlotte"])
    await repo.list_recipes()
    recipe = await repo.mark_cooked("page-0", person="Philip", day="2026-11-19", stars=4, note="  mehr   Chili ")
    props = fake.updates[-1][1]["properties"]
    assert props["Zuletzt gekocht"] == {"date": {"start": "2026-11-19"}}
    assert props["bewertung philip"] == {"number": 4}  # the name as it is in Notion
    assert props["Notiz"]["rich_text"][0]["text"]["content"] == "01.11.2026 Charlotte: lecker\n19.11.2026 Philip: mehr Chili"
    assert recipe.last_cooked == "2026-11-19" and recipe.ratings == (("Philip", 4),)

    recipe = await repo.set_rating("page-0", "Charlotte", 5)
    assert fake.updates[-1][1] == {"properties": {"Bewertung Charlotte": {"number": 5}}}
    assert recipe.ratings == (("Philip", 4), ("Charlotte", 5))
    recipe = await repo.set_rating("page-0", "Philip", None)
    assert recipe.ratings == (("Charlotte", 5),)



class StubLog:
    def __init__(self, fail=False):
        self.added, self.fail = [], fail

    async def add(self, **entry):
        if self.fail:
            from notion_client import APIErrorCode, APIResponseError
            raise APIResponseError(APIErrorCode.ValidationError, 400, "kaputt", httpx.Headers(), "")
        self.added.append(entry)


async def test_mark_cooked_writes_the_log():
    fake = FakeNotion(total=1)
    fake.recipe_schema |= {"Zuletzt gekocht": {"type": "date"}}
    repo = make_repo(fake, people=["Philip"])
    repo.cook_log = StubLog()
    await repo.list_recipes()
    recipe = await repo.mark_cooked("page-0", person="Philip", day="2026-11-20", stars=4, source="Nachgetragen")
    assert recipe.last_cooked == "2026-11-20"
    assert repo.cook_log.added == [{"recipe_id": "page-0", "name": "Rezept 000", "day": "2026-11-20",
                                    "person": "Philip", "stars": 4, "note": None, "source": "Nachgetragen"}]

    repo.cook_log = StubLog(fail=True)  # the recipe still counts as cooked
    recipe = await repo.mark_cooked("page-0", person="Philip", day="2026-11-23")
    assert recipe.last_cooked == "2026-11-23"

def test_long_notes_drop_the_oldest_lines():
    from koch_guru.notion_repo import NOTE_LIMIT, append_note
    current = "\n".join(f"{n:02d}.01.2026 Philip: " + "x" * 200 for n in range(1, 40))
    result = append_note(current, "19.11.2026 Philip: neu")
    assert len(result) <= NOTE_LIMIT and result.endswith("neu") and not result.startswith("01.01")


async def test_own_photo_becomes_the_cover():
    fake = FakeNotion(total=3)
    repo = make_repo(fake)
    recipes = await repo.list_recipes()
    target = recipes[0]
    updated = await repo.set_cover_photo(target.id, b"jpeg-bytes", "image/jpeg")
    assert fake.uploads == [{"mode": "single_part", "filename": "titelbild.jpg", "content_type": "image/jpeg"}]
    assert fake.sent[0][0] == "fu-1" and b"jpeg-bytes" in fake.sent[0][2]
    assert fake.updates[-1] == (target.id, {"cover": {"type": "file_upload", "file_upload": {"id": "fu-1"}}})
    assert updated.cover == "https://files.notion.so/fu-1.jpg?X-Amz-Signature=1"
    cached = next(r for r in await repo.list_recipes() if r.id == target.id)
    assert cached.cover == updated.cover and fake.query_calls == 1  # no reload needed


async def test_edit_name_emoji_tags_origin_and_link():
    fake = FakeNotion(total=3)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    updated = await repo.update_details(
        target.id, name="Kürbis-Dal", emoji="🍛", tags=["Veggie", "Schnell"], origin=["Green Feast"], link=None)
    page_id, body = fake.updates[-1]
    assert page_id == target.id
    assert body["properties"] == {
        "Name": {"title": [{"type": "text", "text": {"content": "Kürbis-Dal"}}]},
        "Tags": {"multi_select": [{"name": "Veggie"}, {"name": "Schnell"}]},
        "Origin": {"multi_select": [{"name": "Green Feast"}]},
        "Link": {"url": None},
    }
    assert body["icon"] == {"type": "emoji", "emoji": "🍛"}
    assert (updated.name, updated.emoji, updated.tags, updated.origin, updated.url) == (
        "Kürbis-Dal", "🍛", ("Veggie", "Schnell"), ("Green Feast",), None)
    assert "Schnell" in repo.tag_options  # new option, offered from now on
    assert fake.query_calls == 1  # the cache was updated, not reloaded


async def test_edit_only_what_was_given_and_remove_emoji():
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    await repo.update_details(target.id, emoji=None, tags=[])
    _, body = fake.updates[-1]
    assert body == {"properties": {"Tags": {"multi_select": []}}, "icon": None}
    await repo.update_details(target.id)  # nothing to change: no request
    assert len(fake.updates) == 1


async def test_remove_cover():
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    await repo.remove_cover(target.id)
    assert fake.updates[-1] == (target.id, {"cover": None})
    assert next(r for r in await repo.list_recipes() if r.id == target.id).cover is None


async def test_editable_fields_follow_the_schema():
    repo = make_repo(FakeNotion(total=1))
    await repo.list_recipes()
    fields = repo.editable_fields
    assert fields["tags"] == {"options": ["Veggie", "Winter"], "multiple": True}
    assert fields["link"] is True and fields["origin"]["multiple"] is True


async def test_save_content_replaces_the_sections_and_fixes_links():
    from koch_guru.notion_repo import content_blocks
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    blocks = content_blocks(ingredients=["1 Süßkartoffel"], steps=["Backen."], minutes=40)
    missing = await repo.save_content(target.id, blocks=blocks, replace_ids=["old-1", "old-2"],
                                      link=[("Süßkartoffel", "🍠", None)], unlink_ids=["ing-2"])
    assert missing == []
    (page_id, children), = fake.appended
    assert page_id == target.id and children == blocks and fake.appended_after == ["old-1"]
    assert fake.deleted == ["old-1", "old-2"]
    relation = fake.updates[-1][1]["properties"]["Ingredients"]["relation"]
    assert {r["id"] for r in relation} == {"ing-1", "ing-3"}  # Süßkartoffel added, Kurkuma (ing-2) removed


async def test_save_content_without_link_changes_only_writes_blocks():
    from koch_guru.notion_repo import content_blocks
    fake = FakeNotion(total=1)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    await repo.save_content(target.id, blocks=content_blocks(ingredients=["1 Ei"], steps=[]), replace_ids=["x"])
    assert fake.updates == [] and fake.deleted == ["x"]


async def test_set_cover_url():
    fake = FakeNotion(total=2)
    repo = make_repo(fake)
    target = (await repo.list_recipes())[0]
    await repo.set_cover_url(target.id, "https://example.com/foto.jpg")
    assert fake.updates[-1] == (target.id, {"cover": {"type": "external", "external": {"url": "https://example.com/foto.jpg"}}})
    assert next(r for r in await repo.list_recipes() if r.id == target.id).cover == "https://example.com/foto.jpg"
    assert fake.query_calls == 1


def test_ratings_are_read_in_quarters():
    from koch_guru.notion_repo import quarter_stars
    assert [quarter_stars(v) for v in (4, 4.25, 4.3, 3.9, 0.25)] == [4, 4.25, 4.25, 4, 0.25]
    assert isinstance(quarter_stars(4.0), int)
