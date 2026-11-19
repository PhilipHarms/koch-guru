"""Web app: login by personal link, API access control and recipe endpoints."""

import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient
from notion_client import APIErrorCode, APIResponseError

from koch_guru.models import Ingredient, Recipe
from koch_guru.notion_repo import IngredientFields
from koch_guru.web.app import create_app
from koch_guru.web.auth import COOKIE_NAME, user_for_key
from koch_guru.web.keys import make_app_users

PHILIP_KEY = "p" * 30
CHARLOTTE_KEY = "c" * 30
USERS = {PHILIP_KEY: "philip", CHARLOTTE_KEY: "charlotte"}

DAL_ID = "11111111-2222-3333-4444-555555555555"
PASTA_ID = "66666666-7777-8888-9999-000000000000"


class FakeRepo:
    def __init__(self, week_supported=True, error=None):
        self.recipes = [
            Recipe(id=DAL_ID, name="Kürbis-Dal", notion_url="https://notion.so/dal",
                   url="https://example.com/dal", tags=("Veggie",), origin=("Green Feast",),
                   ingredients=("Kürbis", "Linsen"), ingredient_ids=("i-kuerbis", "i-linsen"),
                   this_week=True, emoji="🍛",
                   created="2026-11-01T10:00:00.000Z"),
            Recipe(id=PASTA_ID, name="Pasta e ceci", notion_url="https://notion.so/pasta"),
        ]
        self.supports_this_week = week_supported
        self.error = error
        self.updates = []
        self.ingredients = {i.id: i for i in [
            Ingredient("i-kuerbis", "Kürbis", icon="🎃"),
            Ingredient("i-linsen", "Linsen", bought=True, bought_on="2026-11-01"),
            Ingredient("i-salz", "Salz"),
        ]}
        self.ingredient_fields = IngredientFields(bought="Bought", bought_on="Gekauft am", extra="Extra")
        self.people = ["Philip", "Charlotte"]
        self.supports_cooked = True
        self.cooked = []

    async def mark_cooked(self, page_id, *, person, today, stars=None, note=None):
        self.cooked.append((page_id, person, today, stars, note))
        ratings = dict(self._recipe(page_id).ratings)
        if stars:
            ratings[person] = stars
        self._set(page_id, last_cooked=today, ratings=tuple(ratings.items()), note=note)

    async def set_rating(self, page_id, person, stars):
        ratings = {p: s for p, s in self._recipe(page_id).ratings if p != person}
        if stars:
            ratings[person] = stars
        self._set(page_id, ratings=tuple(ratings.items()))

    def _recipe(self, page_id):
        return next(r for r in self.recipes if r.id == page_id)

    def _set(self, page_id, **changes):
        self.recipes = [dataclasses.replace(r, **changes) if r.id == page_id else r for r in self.recipes]

    async def set_bought(self, ingredient_id, value, *, today):
        self.ingredients[ingredient_id] = dataclasses.replace(
            self.ingredients[ingredient_id], bought=value, bought_on=today if value else None)
        return self.ingredients[ingredient_id]

    async def add_extra(self, name):
        added = Ingredient(f"i-{name.lower()}", name, extra=True)
        self.ingredients[added.id] = added
        return added

    async def list_recipes(self, *, force_refresh=False):
        if self.error:
            raise self.error
        return self.recipes

    async def set_this_week(self, page_id, value):
        self.updates.append((page_id, value))
        self.recipes = [dataclasses.replace(r, this_week=value) if r.id == page_id else r
                        for r in self.recipes]

    ingredient_icons = {"Kürbis": "🎃", "Linsen": "🫘"}
    ingredient_names = ["Kürbis", "Linsen", "Salz"]

    async def save_generated(self, page_id, *, draft, link, cover=None, replace_ids=(), unlink_ids=(), new_link=None):
        self.saved = (page_id, draft, link, cover)
        self.saved_changes = {"replace_ids": list(replace_ids), "unlink_ids": list(unlink_ids), "new_link": new_link}
        return [entry[0] for entry in link if entry[0] == "Unbekannt"]

    async def page_blocks(self, page_id, *, refresh=False):
        self.content_requests = getattr(self, "content_requests", []) + [page_id]
        self.refreshed = getattr(self, "refreshed", 0) + int(refresh)
        return [
            {"id": "b1", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Zutaten"}]}},
            {"id": "b2", "type": "bulleted_list_item",
             "bulleted_list_item": {"rich_text": [{"plain_text": "500 g Kürbis"}]}},
            {"id": "b3", "type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Zubereitung"}]}},
            {"id": "b4", "type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "Kochen."}]}},
        ]

    async def clear_this_week(self):
        planned = [r for r in self.recipes if r.this_week]
        for r in planned:
            await self.set_this_week(r.id, False)
        return len(planned)


def client(repo=None, users=USERS, http=None, llm=None):
    return TestClient(create_app(repo=repo or FakeRepo(), users=users, http=http, llm=llm),
                      base_url="https://testserver")


def signed_in(repo=None, key=PHILIP_KEY, http=None, llm=None):
    c = client(repo, http=http, llm=llm)
    c.cookies.set(COOKIE_NAME, key)
    return c


def test_login_link_sets_cookie_and_redirects():
    c = client()
    response = c.get(f"/login/{PHILIP_KEY}", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert f"{COOKIE_NAME}={PHILIP_KEY}" in cookie
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=lax" in cookie.lower()
    assert c.get("/api/me").json() == {"user": "philip", "name": "Philip"}


def test_wrong_login_link_is_rejected():
    response = client().get("/login/" + "x" * 30, follow_redirects=False)
    assert response.status_code == 404
    assert COOKIE_NAME not in response.headers.get("set-cookie", "")


@pytest.mark.parametrize("path", ["/api/me", "/api/recipes", f"/api/recipes/{DAL_ID}"])
def test_api_needs_login(path):
    assert client().get(path).status_code == 401


def test_api_rejects_unknown_cookie():
    assert signed_in(key="z" * 30).get("/api/me").status_code == 401


def test_second_user_is_recognised():
    assert signed_in(key=CHARLOTTE_KEY).get("/api/me").json()["name"] == "Charlotte"


def test_logout_clears_cookie():
    c = client()
    c.get(f"/login/{PHILIP_KEY}")
    assert c.get("/api/me").status_code == 200
    c.get("/logout")
    assert c.get("/api/me").status_code == 401


def test_list_recipes():
    data = signed_in().get("/api/recipes").json()
    assert data["week_supported"] is True
    dal, pasta = data["recipes"]
    assert dal == {
        "id": DAL_ID, "name": "Kürbis-Dal", "link": "https://example.com/dal",
        "source_url": "https://example.com/dal", "notion_url": "https://notion.so/dal",
        "tags": ["Veggie"], "origin": ["Green Feast"], "ingredients": ["Kürbis", "Linsen"],
        "this_week": True, "emoji": "🍛", "image": None, "created": "2026-11-01T10:00:00.000Z",
        "last_cooked": None, "ratings": {}, "note": None,
    }
    assert pasta["link"] == "https://notion.so/pasta" and pasta["emoji"] is None
    assert data["people"] == ["Philip", "Charlotte"] and data["cooked_supported"] is True


def test_get_recipe_accepts_id_without_dashes():
    c = signed_in()
    assert c.get(f"/api/recipes/{PASTA_ID.replace('-', '')}").json()["name"] == "Pasta e ceci"
    assert c.get("/api/recipes/unknown").status_code == 404


def test_put_recipe_on_weekly_list():
    repo = FakeRepo()
    response = signed_in(repo).patch(f"/api/recipes/{PASTA_ID}", json={"this_week": True})
    assert response.status_code == 200
    assert response.json()["this_week"] is True
    assert repo.updates == [(PASTA_ID, True)]


def test_week_update_validates_body_and_support():
    assert signed_in().patch(f"/api/recipes/{PASTA_ID}", json={"this_week": "vielleicht"}).status_code == 422
    no_week = signed_in(FakeRepo(week_supported=False))
    assert no_week.patch(f"/api/recipes/{PASTA_ID}", json={"this_week": True}).status_code == 409
    assert no_week.post("/api/week/clear").status_code == 409


def test_clear_week():
    repo = FakeRepo()
    assert signed_in(repo).post("/api/week/clear").json() == {"cleared": 1}
    assert not any(r.this_week for r in repo.recipes)


def test_notion_errors_become_clear_responses():
    def error(code, status):
        return APIResponseError(code=code, status=status, message="x",
                                headers=httpx.Headers(), raw_body_text="{}")

    limited = signed_in(FakeRepo(error=error(APIErrorCode.RateLimited, 429))).get("/api/recipes")
    assert limited.status_code == 503 and limited.headers["retry-after"] == "2"
    denied = signed_in(FakeRepo(error=error(APIErrorCode.RestrictedResource, 403))).get("/api/recipes")
    assert denied.status_code == 502


def test_placeholder_page_until_front_end_exists():
    assert client().get("/").status_code == 401
    assert "Hallo Philip" in signed_in().get("/").text


def test_healthcheck_without_login():
    assert client().get("/healthz").json() == {"status": "ok"}


def test_user_for_key():
    assert user_for_key(USERS, PHILIP_KEY) == "philip"
    assert user_for_key(USERS, None) is None
    assert user_for_key(USERS, "") is None
    assert user_for_key(USERS, PHILIP_KEY[:-1]) is None


def test_make_app_users_produces_valid_setting():
    from koch_guru.config import _parse_app_users

    users = _parse_app_users(make_app_users(["Philip", "charlotte"]))
    assert sorted(users.values()) == ["charlotte", "philip"]
    assert all(len(key) >= 40 for key in users)


def test_built_front_end_is_served_with_spa_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=app></div>")
    (tmp_path / "assets" / "app-123.js").write_text("console.log(1)")
    (tmp_path / "sw.js").write_text("// sw")
    c = TestClient(create_app(repo=FakeRepo(), users=USERS, static_dir=tmp_path))

    for path in ("/", "/rezepte", "/woche"):
        response = c.get(path)
        assert response.status_code == 200 and "id=app" in response.text
        assert response.headers["cache-control"] == "no-cache"
    asset = c.get("/assets/app-123.js")
    assert "immutable" in asset.headers["cache-control"]
    assert c.get("/sw.js").headers["cache-control"] == "no-cache"
    # API paths never fall back to the app shell.
    assert c.get("/api/unknown").status_code in (401, 404)
    c.cookies.set(COOKIE_NAME, PHILIP_KEY)
    assert c.get("/api/unknown").status_code == 404
    assert c.get("/api/me").status_code == 200


SIGNED = "https://prod-files-secure.s3.us-west-2.amazonaws.com/ws/file-1/dal.jpg?X-Amz-Signature={}"


def with_cover(repo, cover):
    repo.recipes = [dataclasses.replace(repo.recipes[0], cover=cover), *repo.recipes[1:]]
    return repo


def test_recipe_content_splits_ingredients_and_steps():
    repo = FakeRepo()
    data = signed_in(repo).get(f"/api/recipes/{DAL_ID}/content").json()
    assert data["ingredients"] == [{"name": "Kürbis", "amount": "500 g", "emoji": "🎃"}]
    assert data["steps"] == [{"text": "Kochen."}]
    assert repo.content_requests == [DAL_ID]
    assert signed_in().get("/api/recipes/unknown/content").status_code == 404
    assert client().get(f"/api/recipes/{DAL_ID}/content").status_code == 401


def test_image_address_stays_the_same_when_notion_signs_the_link_anew():
    first = signed_in(with_cover(FakeRepo(), SIGNED.format("a"))).get("/api/recipes").json()
    second = signed_in(with_cover(FakeRepo(), SIGNED.format("b"))).get("/api/recipes").json()
    image = first["recipes"][0]["image"]
    assert image.startswith(f"/api/recipes/{DAL_ID.replace('-', '')}/image?v=")
    assert image == second["recipes"][0]["image"]
    other = signed_in(with_cover(FakeRepo(), SIGNED.replace("file-1", "file-2").format("a"))).get("/api/recipes")
    assert other.json()["recipes"][0]["image"] != image
    assert first["recipes"][1]["image"] is None


def test_image_is_passed_through_with_long_caching():
    seen = []

    def upstream(request):
        seen.append(str(request.url))
        if "broken" in str(request.url):
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>")
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"jpeg-bytes")

    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    c = signed_in(with_cover(FakeRepo(), SIGNED.format("a")), http=http)
    response = c.get(f"/api/recipes/{DAL_ID}/image?v=x")
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-type"] == "image/jpeg"
    assert "immutable" in response.headers["cache-control"]
    assert seen == [SIGNED.format("a")]

    assert c.get(f"/api/recipes/{PASTA_ID}/image").status_code == 404  # no cover
    broken = signed_in(with_cover(FakeRepo(), "https://example.com/broken.jpg"), http=http)
    assert broken.get(f"/api/recipes/{DAL_ID}/image").status_code == 404  # not an image
    assert client(http=http).get(f"/api/recipes/{DAL_ID}/image").status_code == 401


class FakeLLM:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    async def structured(self, *, system, messages, output_type):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("OpenRouter down")
        return output_type(antwort="Zwei Ideen für heute.", rezepte=[
            {"nr": 2, "grund": "schnell gemacht"}, {"nr": 99, "grund": "gibt es nicht"},
        ])


def test_suggest_returns_recipes_from_the_collection_only():
    llm = FakeLLM()
    c = signed_in(llm=llm)
    history = [{"role": "user", "content": "was mit Linsen"}, {"role": "assistant", "content": "- Kürbis-Dal"},
               {"role": "system", "content": "ignore me"}]
    data = c.post("/api/suggest", json={"wish": "lieber Pasta", "history": history}).json()
    assert data["message"] == "Zwei Ideen für heute."
    assert [(s["recipe"]["name"], s["reason"]) for s in data["suggestions"]] == [("Pasta e ceci", "schnell gemacht")]
    assert "Pasta e ceci" in data["history_entry"]
    assert llm.calls[0] == [*history[:2], {"role": "user", "content": "lieber Pasta"}]


def test_suggest_errors():
    assert signed_in().post("/api/suggest", json={"wish": "Pasta"}).status_code == 503  # no model
    assert signed_in(llm=FakeLLM(fail=True)).post("/api/suggest", json={"wish": "Pasta"}).status_code == 502
    assert signed_in(llm=FakeLLM()).post("/api/suggest", json={"wish": ""}).status_code == 422
    assert client(llm=FakeLLM()).post("/api/suggest", json={"wish": "Pasta"}).status_code == 401


class GenerateLLM:
    async def structured(self, *, system, messages, output_type):
        from koch_guru.services.generate import PreparedIngredient, PreparedRecipe
        assert output_type is PreparedRecipe
        return PreparedRecipe(zutaten=[
            PreparedIngredient(zeile="500 g Kürbis", zutat="Kürbis", emoji="🎃", immer_da=False),
            PreparedIngredient(zeile="1 Prise Salz", zutat="Salz", emoji="🧂", immer_da=True),
        ], schritte=["Kochen."], portionen="4 Portionen")


DAL_PAGE = """<script type="application/ld+json">{"@type": "Recipe", "name": "Dal",
 "recipeIngredient": ["500 g Kürbis", "Salz"], "recipeInstructions": "Kochen."}</script>"""


def test_generate_preview_and_save():
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=DAL_PAGE, headers={"content-type": "text/html"})))
    repo = FakeRepo()
    c = signed_in(repo, http=http, llm=GenerateLLM())
    preview = c.post(f"/api/recipes/{DAL_ID}/generate").json()
    assert preview["source"] == "https://example.com/dal"
    assert [(i["zutat"], i["status"], i["include"]) for i in preview["ingredients"]] == [
        ("Kürbis", "linked", True), ("Salz", "existing", False),
    ]
    assert preview["image"] is None  # the test page has no photo
    body = {"url": preview["url"], "servings": preview["servings"], "minutes": None, "steps": preview["steps"],
            "cover": "https://example.com/dal.jpg",
            "ingredients": [{"line": i["line"], "zutat": i["zutat"], "emoji": i["emoji"], "link": i["include"]}
                            for i in preview["ingredients"]] + [{"line": "1 Stück", "zutat": "Unbekannt", "link": True}]}
    saved = c.post(f"/api/recipes/{DAL_ID}/generate/save", json=body).json()
    assert saved["not_created"] == ["Unbekannt"]
    assert saved["recipe"]["id"] == DAL_ID
    page_id, draft, link, cover = repo.saved
    assert cover == "https://example.com/dal.jpg"
    assert page_id == DAL_ID and draft.ingredients == ["500 g Kürbis", "1 Prise Salz", "1 Stück"]
    assert draft.url == "https://example.com/dal" and draft.servings == "4 Portionen"
    assert link == [("Kürbis", "🎃", None), ("Unbekannt", None, None)]


class CutOffLLM:
    async def structured(self, *, system, messages, output_type):
        from koch_guru.llm import ModelError
        raise ModelError("Die Antwort war zu lang und wurde abgeschnitten.")


def test_generate_errors():
    assert signed_in().post(f"/api/recipes/{DAL_ID}/generate").status_code == 503  # no model
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=DAL_PAGE, headers={"content-type": "text/html"})))
    cut = signed_in(http=http, llm=CutOffLLM()).post(f"/api/recipes/{DAL_ID}/generate")
    assert cut.status_code == 502 and cut.json()["detail"] == "Die Antwort war zu lang und wurde abgeschnitten."
    pasta = signed_in(llm=GenerateLLM()).post(f"/api/recipes/{PASTA_ID}/generate")  # no link, no photos
    assert pasta.status_code == 422 and "weder einen Link" in pasta.json()["detail"]
    assert client(llm=GenerateLLM()).post(f"/api/recipes/{DAL_ID}/generate").status_code == 401


def test_shopping_list_groups_week_recipes_with_amounts():
    repo = FakeRepo()
    data = signed_in(repo).get("/api/shopping-list").json()
    (group,) = data["groups"]
    assert group["recipe_id"] == DAL_ID
    assert [(i["name"], i["amount"], i["done"], i["icon"]) for i in group["items"]] == [
        ("Kürbis", "500 g", False, "🎃"),  # amount from the recipe page
        ("Linsen", None, True, None),
    ]
    assert data["open"] == 1 and data["extras"] == []
    assert data["can_check"] and data["can_add"]


def test_tick_off_and_add_own_items():
    repo = FakeRepo()
    c = signed_in(repo)
    ticked = c.patch("/api/ingredients/i-kuerbis", json={"bought": True}).json()
    assert ticked["id"] == "i-kuerbis" and ticked["done"] is True
    assert repo.ingredients["i-kuerbis"].bought_on is not None
    assert c.patch("/api/ingredients/i-nix", json={"bought": True}).status_code == 404

    added = c.post("/api/extras", json={"name": "  Spül   mittel "}).json()
    assert added["name"] == "Spül mittel" and added["done"] is False
    assert [e["name"] for e in c.get("/api/shopping-list").json()["extras"]] == ["Spül mittel"]
    assert c.post("/api/extras", json={"name": "   "}).status_code == 422


def test_shopping_list_without_the_fields():
    repo = FakeRepo()
    repo.ingredient_fields = IngredientFields()
    c = signed_in(repo)
    data = c.get("/api/shopping-list").json()
    assert data["can_check"] is False and data["can_add"] is False
    assert c.patch("/api/ingredients/i-kuerbis", json={"bought": True}).status_code == 409
    assert c.post("/api/extras", json={"name": "Spülmittel"}).status_code == 409
    assert client().get("/api/shopping-list").status_code == 401


def test_generate_again_from_a_corrected_link():
    asked = []

    def site(request):
        asked.append(str(request.url))
        return httpx.Response(200, text=DAL_PAGE, headers={"content-type": "text/html"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(site))
    repo = FakeRepo()
    c = signed_in(repo, http=http, llm=GenerateLLM())
    preview = c.post(f"/api/recipes/{DAL_ID}/generate", json={"again": True, "link": " https://example.org/dal "}).json()
    assert asked == ["https://example.org/dal"]
    assert preview["replaces"] == {"info": False, "ingredients": 1, "steps": 1}
    assert preview["unlink"] == [{"id": "i-linsen", "name": "Linsen"}]  # the new version has no lentils
    assert repo.refreshed == 1  # reads the page fresh, not from the cache

    body = {"url": preview["url"], "servings": None, "minutes": None, "steps": preview["steps"],
            "ingredients": [{"line": i["line"], "zutat": i["zutat"], "emoji": i["emoji"], "link": i["include"]}
                            for i in preview["ingredients"]],
            "replace": True, "unlink": ["i-linsen", "i-fremd"], "new_link": "https://example.org/dal",
            "cover": "https://example.org/dal.jpg", "replace_cover": True}
    c.post(f"/api/recipes/{DAL_ID}/generate/save", json=body)
    assert repo.saved_changes == {"replace_ids": ["b1", "b2", "b3", "b4"], "unlink_ids": ["i-linsen"],
                                  "new_link": "https://example.org/dal"}
    assert repo.saved[3] == "https://example.org/dal.jpg"


def test_generate_again_rejects_a_link_that_is_no_web_address():
    repo = FakeRepo()
    c = signed_in(repo, llm=GenerateLLM())
    answer = c.post(f"/api/recipes/{DAL_ID}/generate", json={"again": True, "link": "instagram dal"})
    assert answer.status_code == 422 and "https://" in answer.json()["detail"]


def test_first_generation_keeps_link_and_content():
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=DAL_PAGE, headers={"content-type": "text/html"})))
    repo = FakeRepo()
    c = signed_in(repo, http=http, llm=GenerateLLM())
    preview = c.post(f"/api/recipes/{DAL_ID}/generate").json()
    assert "replaces" not in preview and "unlink" not in preview
    body = {"url": preview["url"], "servings": None, "minutes": None, "steps": preview["steps"],
            "ingredients": [], "new_link": "https://example.com/dal"}  # unchanged link
    c.post(f"/api/recipes/{DAL_ID}/generate/save", json=body)
    assert repo.saved_changes == {"replace_ids": [], "unlink_ids": [], "new_link": None}


def test_cooked_with_stars_and_note_for_the_signed_in_person():
    repo = FakeRepo()
    data = signed_in(repo, key=CHARLOTTE_KEY).post(
        f"/api/recipes/{DAL_ID}/cooked", json={"stars": 4, "note": "mehr Chili"}).json()
    (page_id, person, day, stars, note), = repo.cooked
    assert (page_id, person, stars, note) == (DAL_ID, "Charlotte", 4, "mehr Chili")
    assert data["last_cooked"] == day and data["ratings"] == {"Charlotte": 4}
    assert signed_in(repo).post(f"/api/recipes/{DAL_ID}/cooked", json={"stars": 6}).status_code == 422


def test_rating_is_only_ever_your_own():
    repo = FakeRepo()
    c = signed_in(repo)  # Philip
    assert c.put(f"/api/recipes/{DAL_ID}/rating", json={"stars": 5}).json()["ratings"] == {"Philip": 5}
    assert c.put(f"/api/recipes/{DAL_ID}/rating", json={"stars": 0}).json()["ratings"] == {}
    repo.people = ["Charlotte"]  # no "Bewertung Philip" in Notion
    assert c.put(f"/api/recipes/{DAL_ID}/rating", json={"stars": 3}).status_code == 409
    repo.supports_cooked = False
    assert c.post(f"/api/recipes/{DAL_ID}/cooked", json={}).status_code == 409


# --- Rezept hinzufügen ----------------------------------------------------------------

class ImportRepo(FakeRepo):
    tag_options = ["Veggie", "Winter", "Schnell"]
    origin_options = ["Green Feast"]

    def __init__(self):
        super().__init__()
        self.created = []
        self.linked = []
        self.covers = []
        self.fail_create = False

    async def find_existing(self, draft):
        from koch_guru.services.importer import normalize_url
        for recipe in self.recipes:
            if draft.url and recipe.url and normalize_url(recipe.url) == normalize_url(draft.url):
                return recipe, "link"
        for recipe in self.recipes:
            if draft.name and recipe.name.casefold() == draft.name.casefold():
                return recipe, "name"
        return None, ""

    async def create_recipe(self, draft):
        if self.fail_create:
            raise APIResponseError(code=APIErrorCode.InternalServerError, status=500, message="kaputt",
                                   headers=httpx.Headers(), raw_body_text="")
        self.created.append(draft)
        recipe = Recipe(id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", name=draft.name,
                        notion_url="https://notion.so/neu", url=draft.url, tags=tuple(draft.tags))
        self.recipes = [*self.recipes, recipe]
        return recipe

    async def link_ingredients(self, page_id, link, *, unlink_ids=()):
        self.linked.append((page_id, list(link)))
        return []

    async def set_cover_photo(self, page_id, data, mime):
        self.covers.append((page_id, data, mime))
        self._set(page_id, cover="https://files.notion.so/titelbild.jpg")


class ImportLLM:
    def __init__(self):
        self.seen = []

    async def structured(self, *, system, messages, output_type):
        from koch_guru.services.generate import PreparedIngredient, PreparedRecipe
        from koch_guru.services.importer import Classification, PhotoRecipe
        self.seen.append(output_type.__name__)
        if output_type is Classification:
            return Classification(tags=["Veggie", "Erfunden"], emoji="🍛")
        if output_type is PhotoRecipe:
            return PhotoRecipe(ist_rezept=True, name="Linsensuppe", zutaten=["200 g Linsen"], schritte=["Kochen."],
                               portionen="2", minuten=30, tags=["Winter"], emoji="🍲", quelle="Green Feast")
        assert output_type is PreparedRecipe
        return PreparedRecipe(zutaten=[
            PreparedIngredient(zeile="500 g Kürbis", zutat="Kürbis", emoji="🎃", immer_da=False),
            PreparedIngredient(zeile="1 Bund Koriander", zutat="Koriander", emoji="🌿", immer_da=False),
            PreparedIngredient(zeile="1 Prise Salz", zutat="Salz", emoji="🧂", immer_da=True),
        ], schritte=["Kürbis würfeln.", "Kochen."], portionen="4 Portionen")


NEW_PAGE = """<script type="application/ld+json">{"@type": "Recipe", "name": "Kürbis-Curry",
 "image": "https://example.org/curry.jpg", "totalTime": "PT40M",
 "recipeIngredient": ["500 g pumpkin", "1 bunch coriander", "salt"], "recipeInstructions": "Cook."}</script>"""


def page_client(text=NEW_PAGE):
    return httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=text, headers={"content-type": "text/html"})))


def test_add_recipe_from_a_link():
    repo, llm = ImportRepo(), ImportLLM()
    c = signed_in(repo, http=page_client(), llm=llm)
    preview = c.post("/api/import", json={"url": " https://example.org/curry "}).json()
    assert preview["name"] == "Kürbis-Curry" and preview["icon"] == "🍛"
    assert preview["tags"] == ["Veggie"] and preview["tag_options"] == ["Veggie", "Winter", "Schnell"]
    assert preview["site"] == "example.org" and preview["from_photo"] is False and preview["similar"] is None
    assert preview["image"] == "https://example.org/curry.jpg" and preview["minutes"] == 40
    assert [(i["zutat"], i["status"], i["include"]) for i in preview["ingredients"]] == [
        ("Kürbis", "existing", True), ("Koriander", "new", True), ("Salz", "existing", False),
    ]
    assert repo.created == []  # nothing in Notion before saving

    body = {"name": preview["name"], "tags": ["Winter", "Gibt es nicht"], "servings": preview["servings"],
            "steps": preview["steps"], "cover": True,
            "ingredients": [{"line": i["line"], "zutat": i["zutat"], "emoji": i["emoji"], "link": i["include"],
                             "aisle": i["aisle"]} for i in preview["ingredients"]]}
    saved = c.post(f"/api/import/{preview['draft_id']}/save", json=body).json()
    (draft,) = repo.created
    assert draft.name == "Kürbis-Curry" and draft.url == "https://example.org/curry"
    assert draft.tags == ["Winter"] and draft.icon == "🍛" and draft.image == "https://example.org/curry.jpg"
    assert draft.ingredients == ["500 g Kürbis", "1 Bund Koriander", "1 Prise Salz"]
    assert draft.servings == "4 Portionen" and draft.total_minutes == 40
    assert repo.linked == [(saved["recipe"]["id"], [("Kürbis", "🎃", None), ("Koriander", "🌿", None)])]
    assert saved["recipe"]["name"] == "Kürbis-Curry" and saved["not_created"] == []
    # The preview is used up: a second tap does not create the recipe twice.
    assert c.post(f"/api/import/{preview['draft_id']}/save", json=body).status_code == 410


def test_add_recipe_without_the_photo_of_the_page():
    repo = ImportRepo()
    c = signed_in(repo, http=page_client(), llm=ImportLLM())
    preview = c.post("/api/import", json={"url": "https://example.org/curry"}).json()
    body = {"name": "Mein Curry", "tags": [], "steps": [], "cover": False, "ingredients": []}
    c.post(f"/api/import/{preview['draft_id']}/save", json=body)
    assert repo.created[0].image is None and repo.created[0].name == "Mein Curry"
    assert repo.linked == []


def test_a_failed_save_can_be_tried_again():
    repo = ImportRepo()
    c = signed_in(repo, http=page_client(), llm=ImportLLM())
    preview = c.post("/api/import", json={"url": "https://example.org/curry"}).json()
    body = {"name": "Curry", "tags": [], "steps": [], "ingredients": []}
    repo.fail_create = True
    assert c.post(f"/api/import/{preview['draft_id']}/save", json=body).status_code == 502
    repo.fail_create = False
    assert c.post(f"/api/import/{preview['draft_id']}/save", json=body).status_code == 200


def test_a_link_already_in_the_collection_is_not_read_again():
    llm = ImportLLM()
    c = signed_in(ImportRepo(), http=page_client(), llm=llm)
    answer = c.post("/api/import", json={"url": "https://www.example.com/dal/"}).json()
    assert answer == {"existing": answer["existing"]} and answer["existing"]["name"] == "Kürbis-Dal"
    assert llm.seen == []


def test_a_recipe_with_the_same_name_is_flagged():
    page = NEW_PAGE.replace("Kürbis-Curry", "Pasta e ceci")
    preview = signed_in(ImportRepo(), http=page_client(page), llm=ImportLLM()).post(
        "/api/import", json={"url": "https://example.org/pasta"}).json()
    assert preview["similar"]["name"] == "Pasta e ceci"


def test_add_recipe_from_photos():
    import base64
    repo, llm = ImportRepo(), ImportLLM()
    c = signed_in(repo, llm=llm)
    photo = {"data": "data:image/jpeg;base64," + base64.b64encode(b"jpeg-bytes").decode(), "type": "image/jpeg"}
    preview = c.post("/api/import", json={"photos": [photo], "caption": "Green Feast, S. 112"}).json()
    assert llm.seen == ["PhotoRecipe", "PreparedRecipe"]
    assert preview["name"] == "Linsensuppe" and preview["origin"] == ["Green Feast"]
    assert preview["from_photo"] is True and preview["site"] is None and preview["url"] is None
    body = {"name": "Linsensuppe", "tags": preview["tags"], "steps": preview["steps"], "ingredients": []}
    c.post(f"/api/import/{preview['draft_id']}/save", json=body)
    (draft,) = repo.created
    assert draft.photos == [(b"jpeg-bytes", "image/jpeg")] and draft.origin == ["Green Feast"]
    assert draft.tags == ["Winter"] and draft.url == ""


def test_add_recipe_input_errors():
    import base64
    c = signed_in(ImportRepo(), llm=ImportLLM())
    assert c.post("/api/import", json={"url": "instagram curry"}).status_code == 422
    assert c.post("/api/import", json={}).status_code == 422
    bad_type = {"data": base64.b64encode(b"x").decode(), "type": "application/pdf"}
    assert c.post("/api/import", json={"photos": [bad_type]}).status_code == 422
    broken = {"data": "kein base64!", "type": "image/jpeg"}
    assert c.post("/api/import", json={"photos": [broken]}).status_code == 422
    assert c.post("/api/import/unbekannt/save", json={"name": "x", "steps": [], "ingredients": []}).status_code == 410
    assert signed_in(ImportRepo()).post("/api/import", json={"url": "https://example.org"}).status_code == 503
    assert client(ImportRepo(), llm=ImportLLM()).post("/api/import", json={"url": "https://example.org"}).status_code == 401
    no_recipe = signed_in(ImportRepo(), http=page_client("<html><body>Hallo</body></html>"), llm=ImportLLM())
    answer = no_recipe.post("/api/import", json={"url": "https://example.org/blog"})
    assert answer.status_code == 422 and "kaum Text" in answer.json()["detail"]


def test_own_photo_as_cover():
    import base64
    repo = ImportRepo()
    c = signed_in(repo)
    data = c.put(f"/api/recipes/{PASTA_ID}/cover",
                 json={"data": base64.b64encode(b"jpeg-bytes").decode(), "type": "image/jpeg"}).json()
    assert repo.covers == [(PASTA_ID, b"jpeg-bytes", "image/jpeg")]
    assert data["image"].startswith(f"/api/recipes/{PASTA_ID.replace('-', '')}/image?v=")
    assert c.put(f"/api/recipes/{PASTA_ID}/cover", json={"data": "eA==", "type": "text/plain"}).status_code == 422
    assert client(repo).put(f"/api/recipes/{PASTA_ID}/cover", json={"data": "eA==", "type": "image/png"}).status_code == 401
