"""Telegram handlers. Kept thin: fetch data, call a service, render the reply."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

import openai
from notion_client import APIErrorCode, APIResponseError
from telegram import InlineKeyboardMarkup, LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from koch_guru.bot.render import (
    WEEK_CALLBACK_PREFIX,
    parse_week_button,
    render_recipe_list,
    render_recommendation,
    toggled_keyboard,
    week_keyboard,
)
from koch_guru.llm import LLMClient
from koch_guru.models import Recipe
from koch_guru.notion_repo import RecipeRepository
from koch_guru.services.conversation import ConversationStore
from koch_guru.services.recommend import recommend

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

HELP_TEXT = (
    "👋 Ich bin dein KochGuru und schlage dir Rezepte aus deiner Notion-Sammlung vor.\n\n"
    "Schreib mir einfach, worauf du Lust hast, zum Beispiel:\n"
    "• <i>Was Schnelles, vegetarisch</i>\n"
    "• <i>Wir haben noch Brokkoli und Feta</i>\n"
    "• <i>Ideen für die Woche, gern mal was Asiatisches</i>\n"
    "Rückfragen wie <i>lieber ohne Fleisch</i> verstehe ich auch.\n\n"
    "Mit 📅 unter einem Vorschlag setzt du das Rezept auf die Wochenliste, mit ✅ wieder runter.\n\n"
    "/woche: Wochenliste anzeigen\n"
    "/woche_leeren: Wochenliste leeren\n"
    "/zufall: vier zufällige Rezepte\n"
    "/neu: Gespräch neu beginnen\n"
    "/aktualisieren: Rezepte neu aus Notion laden"
)


@dataclass
class Services:
    repo: RecipeRepository
    llm: LLMClient
    conversations: ConversationStore = field(default_factory=ConversationStore)
    allowed_user_ids: frozenset[int] = frozenset()


def services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.bot_data["services"]


async def reply_html(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW, reply_markup=markup
    )


def keyboard_for(svc: Services, recipes: list[Recipe]) -> InlineKeyboardMarkup | None:
    return week_keyboard(recipes) if svc.repo.supports_this_week else None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_html(update, HELP_TEXT)


async def random_recipes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = services(context)
    recipes = await svc.repo.list_recipes()
    if not recipes:
        await reply_html(update, "In deiner Rezeptsammlung ist noch nichts drin.")
        return
    picks = random.sample(recipes, min(4, len(recipes)))
    await reply_html(
        update, render_recipe_list("Hier sind ein paar zufällige Ideen:", picks), keyboard_for(svc, picks)
    )


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    recipes = await services(context).repo.list_recipes(force_refresh=True)
    with_ingredients = sum(1 for r in recipes if r.ingredients)
    await reply_html(
        update,
        f"Erledigt, {len(recipes)} Rezepte neu aus Notion geladen, "
        f"{with_ingredients} davon mit Zutaten.",
    )


async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    wish = (message.text or "").strip()
    if not wish:
        return
    await message.chat.send_action(ChatAction.TYPING)

    svc = services(context)
    chat_id = update.effective_chat.id
    recipes = await svc.repo.list_recipes()
    result = await recommend(wish, recipes, svc.llm, history=svc.conversations.history(chat_id))
    svc.conversations.add_exchange(chat_id, wish, result.as_history())
    await reply_html(
        update,
        render_recommendation(result),
        keyboard_for(svc, [s.recipe for s in result.suggestions]),
    )


async def reset_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    services(context).conversations.reset(update.effective_chat.id)
    await reply_html(update, "Alles klar, wir fangen von vorn an. Worauf hast du Lust?")


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = services(context)
    if not svc.repo.supports_this_week:
        await reply_html(update, "In deiner Notion-Datenbank gibt es keine Checkbox „This Week?“.")
        return
    planned = [r for r in await svc.repo.list_recipes(force_refresh=True) if r.this_week]
    if not planned:
        await reply_html(update, "Auf der Wochenliste steht gerade nichts.")
        return
    await reply_html(update, render_recipe_list("Diese Woche geplant:", planned), keyboard_for(svc, planned))


async def week_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    svc = services(context)
    if not svc.repo.supports_this_week:
        await reply_html(update, "In deiner Notion-Datenbank gibt es keine Checkbox „This Week?“.")
        return
    count = await svc.repo.clear_this_week()
    text = "Die Wochenliste war schon leer." if count == 0 else (
        f"Erledigt, {count} {'Rezept' if count == 1 else 'Rezepte'} von der Wochenliste genommen."
    )
    await reply_html(update, text)


async def toggle_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Button under a suggestion: put the recipe on the weekly list or take it off."""
    query = update.callback_query
    svc = services(context)
    if update.effective_user is None or update.effective_user.id not in svc.allowed_user_ids:
        await query.answer("Dieser Bot ist privat.")
        return

    markup = query.message.reply_markup if query.message else None
    rows = markup.inline_keyboard if markup else ()
    button = next((b for row in rows for b in row if b.callback_data == query.data), None)
    if button is None:
        await query.answer()
        return

    name, on_list = parse_week_button(button)
    page_id = query.data.removeprefix(WEEK_CALLBACK_PREFIX)
    await svc.repo.set_this_week(page_id, not on_list)
    await query.answer(
        f"{name} ist runter von der Wochenliste." if on_list else f"{name} steht auf der Wochenliste."
    )
    await query.edit_message_reply_markup(toggled_keyboard(markup, query.data, not on_list))


async def unsupported(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_html(
        update, "Das verstehe ich noch nicht. Schreib mir einfach als Text, worauf du Lust hast."
    )


async def not_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is None or update.effective_message is None:
        return
    log.info("Nachricht von nicht freigeschaltetem Nutzer %s ignoriert.", user.id)
    await update.effective_message.reply_text(
        "Dieser Bot ist privat.\n"
        f"Deine Telegram-ID ist {user.id}. Zum Freischalten muss sie in ALLOWED_USER_IDS stehen."
    )


def error_text(error: BaseException | None) -> str:
    """User-facing message. Only allowed users see it, so it may hint at the cause."""
    if isinstance(error, APIResponseError) and error.code == APIErrorCode.RestrictedResource:
        return (
            "Notion lässt den Bot das nicht tun. Prüf in den Einstellungen der Notion-Integration, "
            "ob „Update content“ aktiviert ist."
        )
    if isinstance(error, APIResponseError):
        return "Notion hat gerade einen Fehler gemeldet. Versuch es gleich nochmal."
    if isinstance(error, openai.AuthenticationError):
        return "OpenRouter lehnt den API-Key ab. Bitte OPENROUTER_API_KEY prüfen."
    if isinstance(error, openai.APIStatusError) and error.status_code == 402:
        return "Das OpenRouter-Guthaben ist aufgebraucht."
    if isinstance(error, openai.APIError):
        return "Die KI ist gerade nicht erreichbar. Versuch es gleich nochmal."
    return "Da ist leider etwas schiefgegangen. Versuch es gleich nochmal."


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    log.error("Fehler bei der Verarbeitung eines Updates", exc_info=error)
    text = error_text(error)

    if isinstance(update, Update) and update.callback_query:
        try:
            await update.callback_query.answer(text[:200], show_alert=True)
        except Exception:  # noqa: BLE001 - never let the error handler raise
            log.exception("Fehlermeldung konnte nicht gesendet werden")
        return

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(text)
        except Exception:  # noqa: BLE001 - never let the error handler raise
            log.exception("Fehlermeldung konnte nicht gesendet werden")
