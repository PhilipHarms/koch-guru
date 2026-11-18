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


def ingredient_page(page_id, name):
    return {"object": "page", "id": page_id, "icon": {"type": "emoji", "emoji": f"E{page_id[-1]}"},
            "properties": {"Name": {"type": "title", "title": text(name)}}}


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
        self.reject_ingredients = False

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
            self.appended.append((path.split("/")[3], json.loads(request.content)["children"]))
            return httpx.Response(200, json={"object": "list", "results": [], "has_more": False, "next_cursor": None})
        if path.startswith("/v1/pages/") and request.method == "GET":
            page_id = path.rsplit("/", 1)[1]
            found = next((p for p in self.pages if p["id"] == page_id), None)
            return httpx.Response(200, json=found) if found else self.error(404, "object_not_found")
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
