"""Telegram handlers. Kept thin: fetch data, call a service, render the reply."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from html import escape
from typing import Any, Awaitable, TypeVar

import httpx
import openai
from notion_client import APIErrorCode, APIResponseError
from telegram import InlineKeyboardMarkup, LinkPreviewOptions, Message, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from koch_guru.bot.render import (
    IMPORT_CALLBACK_PREFIX,
    WEEK_CALLBACK_PREFIX,
    import_keyboard,
    parse_week_button,
    recipe_link,
    render_draft_preview,
    render_recipe_list,
    render_recommendation,
    toggled_keyboard,
    week_keyboard,
)
from koch_guru.llm import LLMClient
from koch_guru.models import Recipe
from koch_guru.notion_repo import RecipeRepository
from koch_guru.services.conversation import ConversationStore
from koch_guru.services.drafts import DraftStore
from koch_guru.services.generate import prepare_import
from koch_guru.services.importer import (
    MAX_PHOTOS,
    PHOTO_TYPES,
    Photo,
    RecipeDraft,
    RecipeImportError,
    find_url,
    import_from_photos,
    import_from_url,
)
from koch_guru.services.recommend import recommend

log = logging.getLogger(__name__)

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
ALBUM_WAIT_SECONDS = 2.0  # photos of one album arrive as separate messages
T = TypeVar("T")

HELP_TEXT = (
    "👋 Ich bin dein KochGuru und schlage dir Rezepte aus deiner Notion-Sammlung vor.\n\n"
    "Schreib mir einfach, worauf du Lust hast, zum Beispiel:\n"
    "• <i>Was Schnelles, vegetarisch</i>\n"
    "• <i>Wir haben noch Brokkoli und Feta</i>\n"
    "• <i>Ideen für die Woche, gern mal was Asiatisches</i>\n"
    "Rückfragen wie <i>lieber ohne Fleisch</i> verstehe ich auch.\n\n"
    "Schick mir einen Link oder ein Foto von einem Rezept (gern auch mehrere Fotos als Album), "
    "dann lege ich es nach kurzer Vorschau in Notion an.\n\n"
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
    http: httpx.AsyncClient | None = None
    drafts: DraftStore = field(default_factory=DraftStore)
    albums: dict[str, list[Any]] = field(default_factory=dict)


def services(context: ContextTypes.DEFAULT_TYPE) -> Services:
    return context.bot_data["services"]


async def reply_html(update: Update, text: str, markup: InlineKeyboardMarkup | None = None) -> None:
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW, reply_markup=markup
    )


def keyboard_for(svc: Services, recipes: list[Recipe]) -> InlineKeyboardMarkup | None:
    return week_keyboard(recipes) if svc.repo.supports_this_week else None


async def with_typing(chat: Any, awaitable: Awaitable[T]) -> T:
    """Show "typing…" until the work is done (Telegram hides it after about five seconds)."""
    async def keep_alive() -> None:
        while True:
            await asyncio.sleep(4)
            await chat.send_action(ChatAction.TYPING)

    await chat.send_action(ChatAction.TYPING)
    task = asyncio.create_task(keep_alive())
    try:
        return await awaitable
    finally:
        task.cancel()


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
    svc = services(context)
    chat_id = update.effective_chat.id
    recipes = await svc.repo.list_recipes()
    result = await with_typing(
        message.chat, recommend(wish, recipes, svc.llm, history=svc.conversations.history(chat_id))
    )
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


def is_allowed(update: Update, svc: Services) -> bool:
    return update.effective_user is not None and update.effective_user.id in svc.allowed_user_ids


async def toggle_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Button under a suggestion: put the recipe on the weekly list or take it off."""
    query = update.callback_query
    svc = services(context)
    if not is_allowed(update, svc):
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


async def import_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A message with a link: read the recipe and show a preview with Save/Discard buttons."""
    message = update.effective_message
    url = find_url(message.text or "")
    if not url:
        return
    svc = services(context)

    async def read() -> RecipeDraft:
        draft = await import_from_url(url, svc.http, svc.llm, svc.repo.tag_options)
        return await prepared(svc, draft)

    try:
        draft = await with_typing(message.chat, read())
    except RecipeImportError as exc:
        await reply_html(update, f"{escape(str(exc))} Das Rezept kann ich so leider nicht übernehmen.")
        return
    await show_draft(update, svc, draft)


async def _download(message: Message) -> Photo | None:
    if message.photo:
        file = await message.photo[-1].get_file()  # largest size
        return bytes(await file.download_as_bytearray()), "image/jpeg"
    document = message.document
    if document and document.mime_type in PHOTO_TYPES:
        file = await document.get_file()
        return bytes(await file.download_as_bytearray()), document.mime_type
    return None


async def photo_import(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A photo (or an album of photos) of a recipe: read it and show a preview."""
    message = update.effective_message
    svc = services(context)
    messages = [message]
    if message.media_group_id:
        album = svc.albums.setdefault(message.media_group_id, [])
        album.append(message)
        if len(album) > 1:
            return  # the first photo of the album handles all of them
        await asyncio.sleep(ALBUM_WAIT_SECONDS)
        messages = svc.albums.pop(message.media_group_id, album)

    async def read() -> RecipeDraft:
        photos = [p for m in messages[:MAX_PHOTOS] if (p := await _download(m))]
        caption = " ".join(m.caption for m in messages if m.caption)
        draft = await import_from_photos(
            photos, caption, svc.llm, svc.repo.tag_options, svc.repo.origin_options
        )
        return await prepared(svc, draft)

    try:
        draft = await with_typing(message.chat, read())
    except RecipeImportError as exc:
        await reply_html(update, escape(str(exc)))
        return
    await show_draft(update, svc, draft)


async def prepared(svc: Services, draft: RecipeDraft) -> RecipeDraft:
    """German lines and the ingredients to link, like "Rezept generieren" in the app."""
    await svc.repo.list_recipes()  # loads the names in the ingredients database
    return await prepare_import(draft, svc.llm, svc.repo.ingredient_names)


async def show_draft(update: Update, svc: Services, draft: RecipeDraft) -> None:
    """Preview with Save/Discard, or a hint if the recipe is already in the collection."""
    existing, reason = await svc.repo.find_existing(draft)
    if reason == "link":
        await reply_html(
            update, f"Das Rezept ist schon in deiner Sammlung: {recipe_link(existing)}",
            keyboard_for(svc, [existing]),
        )
        return

    preview = render_draft_preview(draft, similar=existing)
    draft_id = svc.drafts.add(draft, preview)
    await reply_html(update, preview, import_keyboard(draft_id))


async def import_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Save or discard a previewed recipe."""
    query = update.callback_query
    svc = services(context)
    if not is_allowed(update, svc):
        await query.answer("Dieser Bot ist privat.")
        return

    action, _, draft_id = query.data.removeprefix(IMPORT_CALLBACK_PREFIX).partition(":")
    pending = svc.drafts.pop(draft_id)
    if pending is None:
        await query.answer("Der Entwurf ist abgelaufen. Schick mir den Link bitte nochmal.", show_alert=True)
        await query.edit_message_reply_markup(None)
        return

    base = pending.preview_html.rsplit("\n\n", 1)[0]  # drop the question at the end
    if action != "save":
        await query.answer("Verworfen.")
        await query.edit_message_text(
            f"{base}\n\n✖️ Verworfen.", parse_mode=ParseMode.HTML, link_preview_options=NO_PREVIEW
        )
        return

    recipe = await svc.repo.create_recipe(pending.draft)
    links = [(link.name, link.emoji) for link in pending.draft.links]
    not_linked = await svc.repo.link_ingredients(recipe.id, links) if links else []
    saved = f"✅ In Notion angelegt: {recipe_link(recipe)}"
    if not_linked:
        saved += (
            f"\n⚠️ Nicht verknüpft: {escape(', '.join(not_linked))}. "
            "Dafür braucht der Bot Schreibrechte auf die Zutaten-Datenbank."
        )
    await query.answer("Gespeichert.")
    await query.edit_message_text(
        f"{base}\n\n{saved}",
        parse_mode=ParseMode.HTML,
        link_preview_options=NO_PREVIEW,
        reply_markup=keyboard_for(svc, [recipe]),
    )


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
            "ob „Update content“ und „Insert content“ aktiviert sind."
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
