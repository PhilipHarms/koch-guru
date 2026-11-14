"""Telegram HTML rendering. Every dynamic value is escaped here."""

from __future__ import annotations

from html import escape

from koch_guru.models import Recipe
from koch_guru.services.recommend import Recommendation


def recipe_link(recipe: Recipe) -> str:
    return f'<a href="{escape(recipe.link, quote=True)}">{escape(recipe.name)}</a>'


def render_recommendation(rec: Recommendation) -> str:
    parts = [escape(rec.message)] if rec.message else []
    for nr, suggestion in enumerate(rec.suggestions, start=1):
        line = f"{nr}. <b>{recipe_link(suggestion.recipe)}</b>"
        if suggestion.reason:
            line += f"\n<i>{escape(suggestion.reason)}</i>"
        parts.append(line)
    return "\n\n".join(parts) or "Dazu habe ich leider nichts Passendes gefunden."


def render_recipe_list(heading: str, recipes: list[Recipe]) -> str:
    lines = [escape(heading), ""]
    lines += [f"{nr}. {recipe_link(r)}" for nr, r in enumerate(recipes, start=1)]
    return "\n".join(lines)
