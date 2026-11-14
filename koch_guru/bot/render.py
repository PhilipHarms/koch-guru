"""Telegram HTML rendering. Every dynamic value is escaped here."""

from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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


# --- Weekly list buttons -------------------------------------------------------------

WEEK_CALLBACK_PREFIX = "cw:"
ON_LIST, OFF_LIST = "✅ ", "📅 "
MAX_LABEL_CHARS = 40


def _label(name: str, on_list: bool) -> str:
    if len(name) > MAX_LABEL_CHARS:
        name = name[: MAX_LABEL_CHARS - 1].rstrip() + "…"
    return (ON_LIST if on_list else OFF_LIST) + name


def week_keyboard(recipes: list[Recipe]) -> InlineKeyboardMarkup | None:
    """One button per recipe to put it on (or take it off) the weekly list."""
    if not recipes:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(_label(r.name, r.this_week), callback_data=WEEK_CALLBACK_PREFIX + r.short_id)]
         for r in recipes]
    )


def parse_week_button(button: InlineKeyboardButton) -> tuple[str, bool]:
    """(recipe name, currently on the list) from a button label."""
    on_list = button.text.startswith(ON_LIST)
    return button.text.removeprefix(ON_LIST).removeprefix(OFF_LIST), on_list


def toggled_keyboard(markup: InlineKeyboardMarkup, callback_data: str, on_list: bool) -> InlineKeyboardMarkup:
    """Same keyboard with the state of one button flipped."""
    rows = []
    for row in markup.inline_keyboard:
        new_row = []
        for button in row:
            if button.callback_data == callback_data:
                name, _ = parse_week_button(button)
                button = InlineKeyboardButton(_label(name, on_list), callback_data=callback_data)
            new_row.append(button)
        rows.append(new_row)
    return InlineKeyboardMarkup(rows)
