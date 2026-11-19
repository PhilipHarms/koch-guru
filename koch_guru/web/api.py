"""JSON API for the web app. Every route needs a signed-in user."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from koch_guru.llm import ModelError
from koch_guru.models import Recipe
from koch_guru.notion_repo import RecipeRepository
from koch_guru.page_content import fold, generated_sections, image_urls, notes_text, parse_content
from koch_guru.services.generate import generate
from koch_guru.services.importer import RecipeDraft, RecipeImportError
from koch_guru.services.recommend import recommend
from koch_guru.services.shopping import amounts_from_content, item_json, shopping_list, today
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


def web_link(url: str | None) -> str | None:
    url = (url or "").strip()
    return url if url.startswith(("https://", "http://")) else None


class GenerateRequest(BaseModel):
    # Generate again, replacing the earlier version; optionally from a corrected link.
    again: bool = False
    link: str | None = Field(default=None, max_length=2000)


@router.post("/recipes/{recipe_id}/generate")
async def generate_recipe(recipe_id: str, request: Request, body: GenerateRequest | None = None) -> dict[str, Any]:
    """Read ingredients and steps from the recipe's link, or its notes and photos. Writes nothing yet."""
    llm = llm_of(request)
    repo = repo_of(request)
    recipe = await find_recipe(repo, recipe_id)
    again = bool(body and body.again)
    link = web_link(recipe.url)
    if body and body.link and body.link.strip():
        link = web_link(body.link)
        if link is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Der Link muss mit http:// oder https:// beginnen."
            )
    blocks = await repo.page_blocks(recipe.id, refresh=again)
    earlier = generated_sections(blocks) if again else {"ids": [], "info": False, "ingredients": 0, "steps": 0}
    # The earlier version is no source for the new one.
    notes_blocks = [b for b in blocks if b.get("id") not in set(earlier["ids"])]
    try:
        result = await generate(
            link=link,
            notes=notes_text(notes_blocks),
            photo_urls=image_urls(blocks),
            http=request.app.state.http,
            llm=llm,
            known=repo.ingredient_names,
            linked=list(recipe.ingredients),
            aisles=repo.ingredient_fields.aisles,
        )
    except RecipeImportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except ModelError as exc:
        log.warning("Rezept generieren: Modell ohne Antwort: %r", exc.__cause__ or exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:  # the model or a site failed in an unexpected way
        log.warning("Rezept generieren fehlgeschlagen: %r", exc, exc_info=True)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Das hat nicht geklappt. Versuch es gleich noch einmal."
        ) from exc
    data = result.as_json()
    if again:
        data["replaces"] = {key: earlier[key] for key in ("info", "ingredients", "steps")}
        # Linked ingredients the new version does not use, e.g. from a wrong link.
        used = {fold(i.existing or i.zutat) for i in result.ingredients if not i.group}
        data["unlink"] = [
            {"id": ingredient_id, "name": name}
            for ingredient_id, name in zip(recipe.ingredient_ids, recipe.ingredients)
            if fold(name) not in used
        ]
    return data


class GeneratedLine(BaseModel):
    line: str = Field(min_length=1, max_length=300)
    zutat: str = Field(default="", max_length=100)
    emoji: str | None = Field(default=None, max_length=16)
    link: bool = False
    aisle: str | None = Field(default=None, max_length=100)  # tag for a new ingredient


class GeneratedSave(BaseModel):
    url: str | None = Field(default=None, max_length=2000)
    servings: str | None = Field(default=None, max_length=100)
    minutes: int | None = Field(default=None, ge=0, le=10_000)
    ingredients: list[GeneratedLine] = Field(max_length=80)
    steps: list[str] = Field(max_length=60)
    cover: str | None = Field(default=None, max_length=2000)  # photo to set as the page cover
    replace_cover: bool = False  # set `cover` even if the page has one
    replace: bool = False  # replace the earlier generated ingredients and steps
    unlink: list[str] = Field(default_factory=list, max_length=100)  # ingredient ids to unlink
    new_link: str | None = Field(default=None, max_length=2000)  # corrected link for the Link field


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
    links = [(i.zutat.strip(), i.emoji, i.aisle) for i in body.ingredients if i.link and i.zutat.strip()]
    may_set_cover = not recipe.cover or body.replace_cover
    cover = body.cover if body.cover and body.cover.startswith("https://") and may_set_cover else None
    # Found again on the fresh page, so nothing else gets deleted.
    replace_ids = generated_sections(await repo.page_blocks(recipe.id, refresh=True))["ids"] if body.replace else []
    linked = {i.replace("-", ""): i for i in recipe.ingredient_ids}
    unlink = [linked[key] for i in body.unlink if (key := i.replace("-", "")) in linked]
    new_link = web_link(body.new_link)
    if new_link == web_link(recipe.url):
        new_link = None
    not_created = await repo.save_generated(
        recipe.id, draft=draft, link=links, cover=cover, replace_ids=replace_ids, unlink_ids=unlink, new_link=new_link
    )
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


# --- Shopping list ---------------------------------------------------------------------

CONTENT_REQUESTS = asyncio.Semaphore(2)  # Notion allows about 3 requests per second


async def week_amounts(repo: RecipeRepository, recipes: list[Recipe]) -> dict[str, dict[str, str]]:
    """Recipe id -> {ingredient name: amount} from the recipe pages. Pages are cached by the repo."""

    async def one(recipe: Recipe) -> tuple[str, dict[str, str]]:
        try:
            async with CONTENT_REQUESTS:
                blocks = await repo.page_blocks(recipe.id)
        except Exception as exc:  # amounts are a bonus; the list works without them
            log.warning("Mengen für %r nicht gelesen: %r", recipe.name, exc)
            return recipe.id, {}
        content = parse_content(blocks, ingredients=recipe.ingredients, icon_by_name=repo.ingredient_icons)
        return recipe.id, amounts_from_content(content, recipe.ingredients)

    return dict(await asyncio.gather(*(one(r) for r in recipes if r.ingredients)))


@router.get("/shopping-list")
async def get_shopping_list(request: Request) -> dict[str, Any]:
    """Ingredients of the recipes of the week, grouped by recipe, plus own items."""
    repo = repo_of(request)
    recipes = [r for r in await repo.list_recipes() if r.this_week]
    fields = repo.ingredient_fields
    return shopping_list(
        recipes,
        repo.ingredients,
        await week_amounts(repo, recipes),
        today=today(),
        can_check=bool(fields.bought),
        can_add=bool(fields.extra),
        aisles=fields.aisles,
    )


class IngredientUpdate(BaseModel):
    bought: bool


@router.patch("/ingredients/{ingredient_id}")
async def update_ingredient(ingredient_id: str, update: IngredientUpdate, request: Request) -> dict[str, Any]:
    """Tick an ingredient off the shopping list, or put it back."""
    repo = repo_of(request)
    await repo.list_recipes()  # loads the ingredients after a restart
    wanted = ingredient_id.replace("-", "")
    found = next((i for i in repo.ingredients if i.replace("-", "") == wanted), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Zutat nicht gefunden")
    if not repo.ingredient_fields.bought:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Die Zutaten-Datenbank hat keine Checkbox „Bought“.")
    return item_json(await repo.set_bought(found, update.bought, today=today()))


class ExtraItem(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.post("/extras")
async def add_extra(item: ExtraItem, request: Request) -> dict[str, Any]:
    """Put an own item, e.g. washing-up liquid, on the shopping list."""
    repo = repo_of(request)
    name = " ".join(item.name.split())
    if not name:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Bitte gib einen Namen ein.")
    await repo.list_recipes()
    if not repo.ingredient_fields.extra:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Eigene Artikel gehen erst, wenn es das Feld „Extra“ gibt.")
    return item_json(await repo.add_extra(name))
