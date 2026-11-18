"""The shopping list: what the recipes of the week need, plus own items.

It is a view on Notion, not a table of its own. An ingredient counts as bought while its
"Bought" checkbox is set; ticking it in the app sets the checkbox and "Gekauft am".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from koch_guru.models import Ingredient, Recipe
from koch_guru.page_content import best_match

try:
    BERLIN: Any = ZoneInfo("Europe/Berlin")
except ZoneInfoNotFoundError:  # slim images without time zone data
    BERLIN = timezone.utc


def today() -> str:
    """Today's date in Berlin as YYYY-MM-DD, for "Gekauft am"."""
    return datetime.now(BERLIN).date().isoformat()


def amounts_from_content(content: Mapping[str, Any], names: Iterable[str]) -> dict[str, str]:
    """Linked ingredient name -> amount, read from the ingredient lines of the recipe page."""
    names = list(names)
    found: dict[str, str] = {}
    for item in content.get("ingredients") or []:
        if "group" in item or not item.get("amount"):
            continue
        name = best_match(item["name"], names)
        if name and name not in found:
            found[name] = item["amount"]
    return found


def item_json(ingredient: Ingredient, *, amount: str | None = None, also: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": ingredient.id,
        "name": ingredient.name,
        "icon": ingredient.icon,
        "amount": amount,
        "done": ingredient.bought,
        "also": also or [],
    }


def shopping_list(
    recipes: Iterable[Recipe],
    ingredients: Mapping[str, Ingredient],
    amounts: Mapping[str, Mapping[str, str]],
    *,
    today: str,
    can_check: bool,
    can_add: bool,
) -> dict[str, Any]:
    """Groups per recipe of the week, then own items.

    An ingredient that several recipes need shows up in each group, with a note on the
    others, and is counted once. Own items stay visible on the day they were ticked off,
    so a wrong tick can be taken back.
    """
    week = [r for r in recipes if r.this_week]
    needed_by: dict[str, list[str]] = {}
    for recipe in week:
        for ingredient_id in dict.fromkeys(recipe.ingredient_ids):
            needed_by.setdefault(ingredient_id, []).append(recipe.name)

    groups = []
    for recipe in week:
        items = []
        for ingredient_id, name in dict(zip(recipe.ingredient_ids, recipe.ingredients)).items():
            ingredient = ingredients.get(ingredient_id)
            if ingredient is None:
                continue
            also = [other for other in needed_by.get(ingredient_id, []) if other != recipe.name]
            items.append(item_json(ingredient, amount=(amounts.get(recipe.id) or {}).get(name), also=also))
        groups.append({"recipe_id": recipe.id, "items": items})

    extras = sorted(
        (i for i in ingredients.values() if i.extra and i.id not in needed_by and (not i.bought or i.bought_on == today)),
        key=lambda i: i.name.casefold(),
    )
    open_ids = {item["id"] for group in groups for item in group["items"] if not item["done"]}
    open_ids |= {i.id for i in extras if not i.bought}
    return {
        "groups": groups,
        "extras": [item_json(i) for i in extras],
        "open": len(open_ids),
        "can_check": can_check,
        "can_add": can_add,
    }
