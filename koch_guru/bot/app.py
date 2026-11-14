"""Builds the Telegram application and wires all dependencies."""

from __future__ import annotations

import logging

from notion_client import AsyncClient
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, MessageHandler, filters

from koch_guru.bot import handlers
from koch_guru.config import Settings, load_settings
from koch_guru.llm import LLMClient
from koch_guru.notion_repo import RecipeRepository

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand("zufall", "Vier zufällige Rezepte"),
    BotCommand("aktualisieren", "Rezepte neu aus Notion laden"),
    BotCommand("start", "Hilfe anzeigen"),
]


def build_application(settings: Settings) -> Application:
    notion = AsyncClient(auth=settings.notion_token)
    repo = RecipeRepository(
        notion,
        settings.notion_database_id,
        settings.properties,
        cache_seconds=settings.recipe_cache_seconds,
    )
    llm = LLMClient.for_openrouter(settings.openrouter_api_key, settings.model)

    async def post_init(app: Application) -> None:
        await repo.connect()
        await app.bot.set_my_commands(COMMANDS)
        log.info("Modell über OpenRouter: %s", llm.model)

    async def post_shutdown(app: Application) -> None:
        await notion.aclose()
        await llm.close()

    app = (
        ApplicationBuilder()
        .token(settings.telegram_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    app.bot_data["services"] = handlers.Services(repo=repo, llm=llm)
    register_handlers(app, settings.allowed_user_ids)
    return app


def register_handlers(app: Application, allowed_user_ids: frozenset[int]) -> None:
    if not allowed_user_ids:
        log.warning(
            "ALLOWED_USER_IDS ist leer: Der Bot antwortet niemandem außer mit der eigenen "
            "Telegram-ID. Trage deine ID in ALLOWED_USER_IDS ein."
        )

    # Only new messages; edits of old messages are ignored.
    allowed = filters.User(user_id=allowed_user_ids) & filters.UpdateType.MESSAGE

    app.add_handler(CommandHandler(["start", "hilfe", "help"], handlers.start, filters=allowed))
    app.add_handler(CommandHandler("zufall", handlers.random_recipes, filters=allowed))
    app.add_handler(CommandHandler("aktualisieren", handlers.refresh, filters=allowed))
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, handlers.suggest))
    app.add_handler(MessageHandler(allowed, handlers.unsupported))
    app.add_handler(
        MessageHandler(filters.UpdateType.MESSAGE & ~filters.User(user_id=allowed_user_ids),
                       handlers.not_allowed)
    )
    app.add_error_handler(handlers.on_error)


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx logs every Telegram poll at INFO, which drowns everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = load_settings()
    app = build_application(settings)
    log.info("KochGuru startet …")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
