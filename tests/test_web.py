"""Web app: login by personal link, API access control and recipe endpoints."""

import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient
from notion_client import APIErrorCode, APIResponseError

from koch_guru.models import Recipe
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
                   ingredients=("Kürbis", "Linsen"), this_week=True, emoji="🍛"),
            Recipe(id=PASTA_ID, name="Pasta e ceci", notion_url="https://notion.so/pasta"),
        ]
        self.supports_this_week = week_supported
        self.error = error
        self.updates = []

    async def list_recipes(self, *, force_refresh=False):
        if self.error:
            raise self.error
        return self.recipes

    async def set_this_week(self, page_id, value):
        self.updates.append((page_id, value))
        self.recipes = [dataclasses.replace(r, this_week=value) if r.id == page_id else r
                        for r in self.recipes]

    async def clear_this_week(self):
        planned = [r for r in self.recipes if r.this_week]
        for r in planned:
            await self.set_this_week(r.id, False)
        return len(planned)


def client(repo=None, users=USERS):
    return TestClient(create_app(repo=repo or FakeRepo(), users=users), base_url="https://testserver")


def signed_in(repo=None, key=PHILIP_KEY):
    c = client(repo)
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
        "this_week": True, "emoji": "🍛",
    }
    assert pasta["link"] == "https://notion.so/pasta" and pasta["emoji"] is None


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
