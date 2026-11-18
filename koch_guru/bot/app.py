"""Builds the Telegram application and wires all dependencies."""

from __future__ import annotations

import logging

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from koch_guru.bot import handlers
from koch_guru.bot.render import IMPORT_CALLBACK_PREFIX, WEEK_CALLBACK_PREFIX
from koch_guru.config import Settings, load_settings
from koch_guru.core import Core, build_core

log = logging.getLogger(__name__)

COMMANDS = [
    BotCommand("woche", "Wochenliste anzeigen"),
    BotCommand("woche_leeren", "Wochenliste leeren"),
    BotCommand("zufall", "Vier zufällige Rezepte"),
    BotCommand("neu", "Gespräch neu beginnen"),
    BotCommand("aktualisieren", "Rezepte neu aus Notion laden"),
    BotCommand("start", "Hilfe anzeigen"),
]


def build_application(settings: Settings, core: Core | None = None) -> Application:
    """Telegram application on top of the shared core.

    Without `core` the bot runs on its own (`run_polling`) and starts and closes
    its own core. With `core` the caller owns the lifecycle: the web server starts
    the core once and then the bot with `start_bot` / `stop_bot`.
    """
    standalone = core is None
    core = core or build_core(settings)

    builder = ApplicationBuilder().token(settings.telegram_token)
    if standalone:
        async def post_init(app: Application) -> None:
            await core.start()
            await app.bot.set_my_commands(COMMANDS)

        async def post_shutdown(app: Application) -> None:
            await core.aclose()

        builder = builder.post_init(post_init).post_shutdown(post_shutdown)

    app = builder.build()
    app.bot_data["services"] = handlers.Services(
        repo=core.repo, llm=core.llm, allowed_user_ids=settings.allowed_user_ids, http=core.http
    )
    register_handlers(app, settings.allowed_user_ids)
    return app


async def start_bot(app: Application) -> None:
    """Start polling inside an already running event loop (used by the web server)."""
    await app.initialize()
    await app.bot.set_my_commands(COMMANDS)
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    log.info("Telegram-Bot läuft.")


async def stop_bot(app: Application) -> None:
    if app.updater and app.updater.running:
        await app.updater.stop()
    if app.running:
        await app.stop()
    await app.shutdown()


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
    app.add_handler(CommandHandler("woche", handlers.week, filters=allowed))
    app.add_handler(CommandHandler("woche_leeren", handlers.week_clear, filters=allowed))
    app.add_handler(CommandHandler("neu", handlers.reset_conversation, filters=allowed))
    # Callback queries are checked against the allowlist inside the handler.
    app.add_handler(CallbackQueryHandler(handlers.toggle_week, pattern=f"^{WEEK_CALLBACK_PREFIX}"))
    app.add_handler(CallbackQueryHandler(handlers.import_decision, pattern=f"^{IMPORT_CALLBACK_PREFIX}"))
    url = filters.Regex(r"https?://")
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND & url, handlers.import_link))
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, handlers.suggest))
    # Non-blocking, so the other photos of an album arrive while the first one waits for them.
    photos = filters.PHOTO | filters.Document.IMAGE
    app.add_handler(MessageHandler(allowed & photos, handlers.photo_import, block=False))
    app.add_handler(MessageHandler(allowed, handlers.unsupported))
    app.add_handler(
        MessageHandler(filters.UpdateType.MESSAGE & ~filters.User(user_id=allowed_user_ids),
                       handlers.not_allowed)
    )
    app.add_error_handler(handlers.on_error)


def configure_logging() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    # httpx logs every Telegram poll at INFO, which drowns everything else.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def run() -> None:
    """Bot only, without the web app (handy for local tests with a second bot token)."""
    configure_logging()
    settings = load_settings()
    app = build_application(settings)
    log.info("KochGuru startet (nur Bot) …")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
