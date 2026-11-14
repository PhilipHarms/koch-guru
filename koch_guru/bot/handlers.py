"""Telegram handlers. Kept thin: fetch data, call a service, render the reply."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import openai
from notion_client import APIResponseError
from telegram import LinkPreviewOptions, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from koch_guru.bot.render import render_recipe_list, render_recommendation
from koch_guru.llm import LLMClient
from koch_guru.notion_repo import RecipeRepository
from koch_guru.services.recommend import recommend

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

HELP_TEXT = (
    "👋 Ich bin dein KochGuru und schlage dir Rezepte aus deiner Notion-Sammlung vor.\n\n"
    "Schreib mir einfach, worauf du Lust hast, zum Beispiel:\n"
    "• <i>Was Schnelles, vegetarisch</i>\n"
    "• <i>Wir haben noch Brokkoli und Feta</i>\n"
    "• <i>Ideen für die Woche, gern mal was Asiatisches</i>\n\n"
    "/zufall: vier zufällige Rezepte\n"
    "/aktualisieren: Rezepte neu aus Notion laden"
)


@dataclass
class Services:
    repo: RecipeRepository
    llm: LLMClient


def services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.bot_data["services"]


async def reply_html(update: Update, text: str) -> None:
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply_html(update, HELP_TEXT)


async def random_recipes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    recipes = await services(context).repo.list_recipes()
    if not recipes:
        await reply_html(update, "In deiner Rezeptsammlung ist noch nichts drin.")
        return
    picks = random.sample(recipes, min(4, len(recipes)))
    await reply_html(update, render_recipe_list("Hier sind ein paar zufällige Ideen:", picks))


async def refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    recipes = await services(context).repo.list_recipes(force_refresh=True)
    await reply_html(update, f"Erledigt, {len(recipes)} Rezepte neu aus Notion geladen.")


async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    wish = (message.text or "").strip()
    if not wish:
        return
    await message.chat.send_action(ChatAction.TYPING)

    svc = services(context)
    recipes = await svc.repo.list_recipes()
    result = await recommend(wish, recipes, svc.llm)
    await reply_html(update, render_recommendation(result))


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

    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(text)
        except Exception:  # noqa: BLE001 - never let the error handler raise
            log.exception("Fehlermeldung konnte nicht gesendet werden")
