"""Telegram HTML rendering. Every dynamic value is escaped here."""

from __future__ import annotations

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from koch_guru.models import Recipe
from koch_guru.services.importer import RecipeDraft
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


# --- Recipe import --------------------------------------------------------------------

IMPORT_CALLBACK_PREFIX = "imp:"
PREVIEW_INGREDIENTS = 8


def render_draft_preview(draft: RecipeDraft, similar: Recipe | None = None) -> str:
    facts = [escape(draft.site) if draft.url else "📷 Foto"]
    if draft.origin:
        facts.append(f"📚 {escape(', '.join(draft.origin))}")
    if draft.total_minutes:
        facts.append(f"⏱ {draft.total_minutes} Min")
    if draft.servings:
        facts.append(f"🍽 {escape(draft.servings)}")

    items = [i for i in draft.ingredients if not i.endswith(":")]  # without group labels
    shown = ", ".join(escape(i) for i in items[:PREVIEW_INGREDIENTS])
    more = len(items) - PREVIEW_INGREDIENTS
    if more > 0:
        shown += f" und {more} weitere"

    lines = [
        f"{draft.icon or '📖'} <b>{escape(draft.name)}</b>",
        " · ".join(facts),
        "",
        f"<b>Tags:</b> {escape(', '.join(draft.tags)) if draft.tags else 'keine passenden gefunden'}",
        f"<b>Zutaten ({len(items)}):</b> {shown}",
        "<b>Zubereitung:</b> " + (f"{len(draft.steps)} Schritte" if draft.steps else "nicht gefunden"),
    ]
    if draft.links:
        new = sum(1 for link in draft.links if link.new)
        linked = f"{len(draft.links)} {'wird' if len(draft.links) == 1 else 'werden'} verknüpft"
        lines.append(f"<b>Zutaten-Datenbank:</b> {linked}" + (f", {new} davon neu angelegt" if new else ""))
    if draft.source == "text":
        lines += ["", "<i>Aus dem Seitentext gelesen, bitte kurz prüfen.</i>"]
    elif draft.source == "photo":
        lines += ["", "<i>Vom Foto gelesen, bitte kurz prüfen. Das Foto hänge ich an die Notion-Seite.</i>"]
    if similar:
        lines += ["", f"⚠️ Ein Rezept mit diesem Namen gibt es schon: {recipe_link(similar)}"]
    lines += ["", "Soll ich das Rezept in Notion anlegen?"]
    return "\n".join(lines)


def import_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("💾 Speichern", callback_data=f"{IMPORT_CALLBACK_PREFIX}save:{draft_id}"),
        InlineKeyboardButton("✖️ Verwerfen", callback_data=f"{IMPORT_CALLBACK_PREFIX}drop:{draft_id}"),
    ]])
