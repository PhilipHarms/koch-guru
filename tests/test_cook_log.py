"""The "Kochprotokoll" against the real notion-client with a mocked Notion."""

import json
from types import SimpleNamespace

import httpx
from notion_client import AsyncClient

from koch_guru import cook_log
from koch_guru.cook_log import NO_PLACE, CookLog

RECIPE_DS = "recipe-ds"
RECIPE_DB = "11111111-2222-3333-4444-555555555555"
ING_DS = "ing-ds"
LOG_DS = "log-ds"


def text(value):
    return [{"plain_text": value}]


class FakeNotion:
    def __init__(self, parent=None, writable=("parent-page",), pages_named=()):
        self.parent = parent or {"type": "page_id", "page_id": "parent-page"}
        self.writable = set(writable)
        self.pages_named = list(pages_named)  # ids of pages titled "Kochprotokoll"
        self.recipe_schema = {
            "Name": {"type": "title"},
            "Ingredients": {"type": "relation", "relation": {"data_source_id": ING_DS}},
        }
        self.log_schema = None
        self.log_title = "Kochprotokoll"
        self.created_databases = []
        self.renames = []
        self.entries = []
        self.fail_entries = False

    @staticmethod
    def error(status, code):
        return httpx.Response(status, json={"object": "error", "status": status, "code": code, "message": code})

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content or b"{}")
        if path == f"/v1/databases/{RECIPE_DB}" and method == "GET":
            return httpx.Response(200, json={"object": "database", "id": RECIPE_DB, "parent": self.parent,
                                             "data_sources": [{"id": RECIPE_DS}]})
        if path == "/v1/databases" and method == "POST":
            if body["parent"]["page_id"] not in self.writable:
                return self.error(404, "object_not_found")
            self.created_databases.append(body)
            schema = body["initial_data_source"]["properties"]
            self.log_schema = {name: {"type": next(iter(prop)), **prop} for name, prop in schema.items()}
            self.log_schema["Rezept"]["relation"] = {
                "data_source_id": RECIPE_DS, "type": "dual_property",
                "dual_property": {"synced_property_id": "rev%3A1", "synced_property_name": "Related to Kochprotokoll"},
            }
            self.recipe_schema["Related to Kochprotokoll"] = {
                "id": "rev%3A1", "type": "relation", "relation": {"data_source_id": LOG_DS}}
            return httpx.Response(200, json={"object": "database", "id": "log-db", "url": "https://notion.so/log",
                                             "data_sources": [{"id": LOG_DS, "name": "Kochprotokoll"}]})
        if path == f"/v1/data_sources/{RECIPE_DS}" and method == "PATCH":
            self.renames.append(body["properties"])
            return httpx.Response(200, json={"object": "data_source", "properties": self.recipe_schema})
        if path == f"/v1/data_sources/{LOG_DS}" and method == "GET":
            if self.log_schema is None:
                return self.error(404, "object_not_found")
            return httpx.Response(200, json={"object": "data_source", "id": LOG_DS, "title": text(self.log_title),
                                             "properties": self.log_schema})
        if path == f"/v1/data_sources/{ING_DS}" and method == "GET":
            return httpx.Response(200, json={"object": "data_source", "id": ING_DS, "title": text("Zutaten"),
                                             "properties": {}})
        if path == "/v1/search" and method == "POST":
            results = [{"object": "page", "id": pid, "properties": {"title": {"type": "title",
                                                                             "title": text("Kochprotokoll")}}}
                       for pid in self.pages_named]
            return httpx.Response(200, json={"object": "list", "results": results, "has_more": False,
                                             "next_cursor": None})
        if path == "/v1/pages" and method == "POST":
            if self.fail_entries:
                return self.error(400, "validation_error")
            self.entries.append(body["properties"])
            return httpx.Response(200, json={"object": "page", "id": f"entry-{len(self.entries)}"})
        if path == f"/v1/data_sources/{LOG_DS}/query" and method == "POST":
            pages = [{"object": "page", "id": f"entry-{i}", "properties": {
                name: {"type": next(iter(value)), **value} for name, value in props.items()}}
                for i, props in enumerate(self.entries)]
            return httpx.Response(200, json={"object": "list", "results": pages, "has_more": False,
                                             "next_cursor": None})
        return self.error(404, "object_not_found")


def make_log(fake, people=("Philip", "Charlotte")):
    client = AsyncClient(auth="secret", client=httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    return CookLog(client, people)


async def connect(log, fake):
    await log.connect(recipe_source_id=RECIPE_DS, recipe_database_id=RECIPE_DB,
                      recipe_schema=fake.recipe_schema, skip_sources={ING_DS})


async def test_created_next_to_the_recipes_and_linked_both_ways():
    fake = FakeNotion()
    log = make_log(fake)
    await connect(log, fake)
    assert log.ready and log.problem is None and log.url == "https://notion.so/log"
    created = fake.created_databases[0]
    assert created["parent"] == {"type": "page_id", "page_id": "parent-page"}
    props = created["initial_data_source"]["properties"]
    assert props["Gericht"] == {"title": {}}
    assert props["Rezept"]["relation"] == {"data_source_id": RECIPE_DS, "type": "dual_property", "dual_property": {}}
    assert [o["name"] for o in props["Wer"]["select"]["options"]] == ["Philip", "Charlotte"]
    assert [o["name"] for o in props["Quelle"]["select"]["options"]] == ["Kochmodus", "Nachgetragen", "Übernommen"]
    assert fake.renames == [{"rev%3A1": {"name": "Kochprotokoll"}}]  # the field in the recipe database


async def test_found_again_through_the_link_without_creating_a_second():
    fake = FakeNotion()
    await connect(make_log(fake), fake)
    log = make_log(fake)
    await connect(log, fake)
    assert log.ready and len(fake.created_databases) == 1


async def test_created_in_a_shared_page_when_the_recipes_parent_is_closed():
    fake = FakeNotion(parent={"type": "workspace", "workspace": True}, writable=("own-page",),
                      pages_named=["own-page"])
    log = make_log(fake)
    await connect(log, fake)
    assert log.ready and fake.created_databases[0]["parent"]["page_id"] == "own-page"


async def test_without_a_place_the_app_says_what_to_do():
    fake = FakeNotion(writable=())
    log = make_log(fake)
    await connect(log, fake)
    assert not log.ready and log.problem == NO_PLACE
    await log.add(recipe_id="r1", name="Dal", day="2026-11-20")  # nothing to write, no error
    assert fake.entries == [] and log.status() == {"ready": False, "url": None, "problem": NO_PLACE}


async def test_a_log_without_link_or_date_is_not_used_and_not_duplicated():
    fake = FakeNotion()
    await connect(make_log(fake), fake)
    del fake.log_schema["Datum"]
    log = make_log(fake)
    await connect(log, fake)
    assert not log.ready and "Datum" in log.problem and len(fake.created_databases) == 1


async def test_entry_with_everything_known():
    fake = FakeNotion()
    log = make_log(fake)
    await connect(log, fake)
    await log.add(recipe_id="r1", name="Kürbis-Dal", day="2026-11-20", person="Philip", stars=4.25,
                  note="  mehr   Chili ", source=cook_log.LATER)
    assert fake.entries == [{
        "Gericht": {"title": [{"type": "text", "text": {"content": "Kürbis-Dal"}}]},
        "Rezept": {"relation": [{"id": "r1"}]},
        "Datum": {"date": {"start": "2026-11-20"}},
        "Wer": {"select": {"name": "Philip"}},
        "Sterne": {"number": 4.25},
        "Notiz": {"rich_text": [{"type": "text", "text": {"content": "mehr Chili"}}]},
        "Quelle": {"select": {"name": "Nachgetragen"}},
    }]


async def test_take_over_last_cooked_for_recipes_without_entries(monkeypatch):
    monkeypatch.setattr(cook_log, "PACE", 0)
    fake = FakeNotion()
    log = make_log(fake)
    await connect(log, fake)
    await log.add(recipe_id="aaaa-1", name="Dal", day="2026-11-20", person="Philip")

    def recipe(rid, name, last):
        return SimpleNamespace(id=rid, short_id=rid.replace("-", ""), name=name, last_cooked=last)

    recipes = [recipe("aaaa-1", "Dal", "2026-11-01"), recipe("bbbb-2", "Pasta", "2026-10-03"),
               recipe("cccc-3", "Nie gekocht", None)]
    assert await log.take_over(recipes) == 1
    added = fake.entries[-1]
    assert added["Rezept"] == {"relation": [{"id": "bbbb-2"}]} and added["Datum"] == {"date": {"start": "2026-10-03"}}
    assert added["Quelle"] == {"select": {"name": "Übernommen"}} and "Wer" not in added
    assert await log.take_over(recipes) == 0  # nothing twice
    assert [(e.recipe_id, e.person, e.source) for e in await log.entries()] == [
        ("aaaa-1", "Philip", "Kochmodus"), ("bbbb-2", None, "Übernommen")]
