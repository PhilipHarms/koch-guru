"""JSON API for the web app. Every route needs a signed-in user."""

from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from koch_guru.models import Recipe
from koch_guru.notion_repo import RecipeRepository
from koch_guru.page_content import image_urls, notes_text, parse_content
from koch_guru.services.generate import generate
from koch_guru.services.importer import RecipeDraft, RecipeImportError
from koch_guru.services.recommend import recommend
from koch_guru.web.auth import current_user, display_name

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", dependencies=[Depends(current_user)])

MAX_IMAGE_BYTES = 15 * 1024 * 1024


def image_version(url: str) -> str:
    """Stays the same while the cover stays the same.

    Notion signs its file links anew on every request, so for those only the path counts.
    """
    parts = urlsplit(url)
    signed = "X-Amz-" in parts.query
    stable = f"{parts.scheme}://{parts.netloc}{parts.path}" if signed else url
    return hashlib.sha256(stable.encode()).hexdigest()[:12]


def image_path(recipe: Recipe) -> str | None:
    if not recipe.cover:
        return None
    return f"/api/recipes/{recipe.short_id}/image?v={image_version(recipe.cover)}"


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
        "image": image_path(recipe),
        "created": recipe.created,
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


@router.get("/recipes/{recipe_id}/content")
async def get_recipe_content(recipe_id: str, request: Request) -> dict[str, Any]:
    """Ingredients, steps and the rest of the Notion page, ready for the recipe screen."""
    repo = repo_of(request)
    recipe = await find_recipe(repo, recipe_id)
    blocks = await repo.page_blocks(recipe.id)
    return parse_content(blocks, ingredients=recipe.ingredients, icon_by_name=repo.ingredient_icons)


@router.get("/recipes/{recipe_id}/image")
async def get_recipe_image(recipe_id: str, request: Request) -> Response:
    """The cover photo, passed through so that it gets a stable address the phone can cache.

    The address carries a version (?v=...), so a new cover gets a new address.
    """
    recipe = await find_recipe(repo_of(request), recipe_id)
    if not recipe.cover or not recipe.cover.startswith(("https://", "http://")):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Kein Foto")
    http: httpx.AsyncClient = request.app.state.http
    try:
        upstream = await http.get(recipe.cover, headers={"Accept": "image/*"})
    except httpx.HTTPError as exc:
        log.warning("Foto von %s nicht geladen: %s", urlsplit(recipe.cover).netloc, exc)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Foto nicht erreichbar") from exc
    media_type = upstream.headers.get("content-type", "").split(";")[0].strip()
    if (
        upstream.status_code != 200
        or not media_type.startswith("image/")
        or len(upstream.content) > MAX_IMAGE_BYTES
    ):
        log.warning("Foto von %s unbrauchbar: %s %s", urlsplit(recipe.cover).netloc,
                    upstream.status_code, media_type)
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Foto nicht erreichbar")
    return Response(
        upstream.content,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


class Wish(BaseModel):
    wish: str = Field(min_length=1, max_length=500)
    # Earlier turns of this conversation, so "lieber ohne Fleisch" refers to the last answer.
    history: list[dict[str, str]] = Field(default_factory=list, max_length=10)


@router.post("/suggest")
async def suggest(wish: Wish, request: Request) -> dict[str, Any]:
    """Recipe ideas for a wish, chosen by Claude from the collection, like in the bot."""
    llm = request.app.state.llm
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Vorschläge sind gerade nicht verfügbar")
    recipes = await repo_of(request).list_recipes()
    history = [
        {"role": turn["role"], "content": turn["content"][:2000]}
        for turn in wish.history
        if turn.get("role") in ("user", "assistant") and turn.get("content")
    ]
    try:
        result = await recommend(wish.wish.strip(), recipes, llm, history=history)
    except Exception as exc:  # the model or OpenRouter failed; the app shows a short note
        log.warning("Vorschläge fehlgeschlagen: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="KochGuru hat gerade keine Antwort. Versuch es gleich noch einmal."
        ) from exc
    return {
        "message": result.message,
        "suggestions": [{"recipe": recipe_json(s.recipe), "reason": s.reason} for s in result.suggestions],
        "history_entry": result.as_history(),
    }


def llm_of(request: Request) -> Any:
    llm = request.app.state.llm
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="KochGuru ist gerade nicht erreichbar")
    return llm


@router.post("/recipes/{recipe_id}/generate")
async def generate_recipe(recipe_id: str, request: Request) -> dict[str, Any]:
    """Read ingredients and steps from the recipe's link, or its notes and photos. Writes nothing yet."""
    llm = llm_of(request)
    repo = repo_of(request)
    recipe = await find_recipe(repo, recipe_id)
    link = recipe.url if recipe.url and recipe.url.startswith(("https://", "http://")) else None
    blocks = await repo.page_blocks(recipe.id)
    try:
        result = await generate(
            link=link,
            notes=notes_text(blocks),
            photo_urls=image_urls(blocks),
            http=request.app.state.http,
            llm=llm,
            known=repo.ingredient_names,
            linked=list(recipe.ingredients),
        )
    except RecipeImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except Exception as exc:  # the model or a site failed in an unexpected way
        log.warning("Rezept generieren fehlgeschlagen: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Das hat nicht geklappt. Versuch es gleich noch einmal."
        ) from exc
    return result.as_json()


class GeneratedLine(BaseModel):
    line: str = Field(min_length=1, max_length=300)
    zutat: str = Field(default="", max_length=100)
    emoji: str | None = Field(default=None, max_length=16)
    link: bool = False


class GeneratedSave(BaseModel):
    url: str | None = Field(default=None, max_length=2000)
    servings: str | None = Field(default=None, max_length=100)
    minutes: int | None = Field(default=None, ge=0, le=10_000)
    ingredients: list[GeneratedLine] = Field(max_length=80)
    steps: list[str] = Field(max_length=60)
    cover: str | None = Field(default=None, max_length=2000)  # photo to set as the page cover


@router.post("/recipes/{recipe_id}/generate/save")
async def save_generated_recipe(recipe_id: str, body: GeneratedSave, request: Request) -> dict[str, Any]:
    """Write the reviewed preview to the Notion page and link the chosen ingredients."""
    repo = repo_of(request)
    recipe = await find_recipe(repo, recipe_id)
    draft = RecipeDraft(
        name=recipe.name,
        url=body.url if body.url and body.url.startswith(("https://", "http://")) else "",
        ingredients=[i.line.strip() for i in body.ingredients if i.line.strip()],
        steps=[s.strip()[:2000] for s in body.steps if s.strip()],
        servings=(body.servings or "").strip() or None,
        total_minutes=body.minutes or None,
    )
    links = [(i.zutat.strip(), i.emoji) for i in body.ingredients if i.link and i.zutat.strip()]
    cover = body.cover if body.cover and body.cover.startswith("https://") and not recipe.cover else None
    not_created = await repo.save_generated(recipe.id, draft=draft, link=links, cover=cover)
    return {"recipe": recipe_json(await find_recipe(repo, recipe.id)), "not_created": not_created}


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
