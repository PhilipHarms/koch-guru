"""JSON API for the web app. Every route needs a signed-in user."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from koch_guru.models import Recipe
from koch_guru.notion_repo import RecipeRepository
from koch_guru.web.auth import current_user, display_name

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])


def recipe_json(recipe: Recipe) -> dict[str, Any]:
    return {
        "id": recipe.id,
        "name": recipe.name,
        "link": recipe.link,
        "source_url": recipe.url,
        "notion_url": recipe.notion_url,
        "tags": list(recipe.tags),
        "origin": list(recipe.origin),
        "ingredients": list(recipe.ingredients),
        "this_week": recipe.this_week,
        "emoji": recipe.emoji,
    }


def repo_of(request: Request) -> RecipeRepository:
    return request.app.state.repo


async def find_recipe(repo: RecipeRepository, recipe_id: str) -> Recipe:
    wanted = recipe_id.replace("-", "")
    for recipe in await repo.list_recipes():
        if recipe.short_id == wanted:
            return recipe
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Rezept nicht gefunden")


@router.get("/me")
async def me(user: str = Depends(current_user)) -> dict[str, str]:
    return {"user": user, "name": display_name(user)}


@router.get("/recipes")
async def list_recipes(request: Request) -> dict[str, Any]:
    repo = repo_of(request)
    recipes = await repo.list_recipes()
    return {
        "recipes": [recipe_json(r) for r in recipes],
        "week_supported": repo.supports_this_week,
    }


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: str, request: Request) -> dict[str, Any]:
    return recipe_json(await find_recipe(repo_of(request), recipe_id))


class RecipeUpdate(BaseModel):
    this_week: bool


@router.patch("/recipes/{recipe_id}")
async def update_recipe(recipe_id: str, update: RecipeUpdate, request: Request) -> dict[str, Any]:
    repo = repo_of(request)
    if not repo.supports_this_week:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Die Datenbank hat keine Wochenliste")
    recipe = await find_recipe(repo, recipe_id)
    await repo.set_this_week(recipe.id, update.this_week)
    return recipe_json(await find_recipe(repo, recipe.id))


@router.post("/week/clear")
async def clear_week(request: Request) -> dict[str, int]:
    repo = repo_of(request)
    if not repo.supports_this_week:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Die Datenbank hat keine Wochenliste")
    return {"cleared": await repo.clear_this_week()}
