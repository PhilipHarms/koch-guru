"""One process for everything: web app (FastAPI on Uvicorn) plus Telegram bot.

The server owns the lifecycle: it starts the shared core once, then the bot's
polling in the same event loop, and on shutdown stops both in reverse order.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from koch_guru.bot.app import build_application, configure_logging, start_bot, stop_bot
from koch_guru.config import Settings, load_settings
from koch_guru.core import build_core
from koch_guru.web.app import create_app

log = logging.getLogger(__name__)

# The built front end (step 4) lands here; until then the server shows a placeholder.
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "dist"


def build_server_app(settings: Settings) -> FastAPI:
    core = build_core(settings)
    bot = build_application(settings, core)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await core.start()
        await start_bot(bot)
        try:
            yield
        finally:
            await stop_bot(bot)
            await core.aclose()

    return create_app(repo=core.repo, users=settings.app_users, lifespan=lifespan, static_dir=STATIC_DIR)


def run() -> None:
    configure_logging()
    settings = load_settings()
    app = build_server_app(settings)
    log.info("KochGuru startet: Web-App auf Port %d und Telegram-Bot …", settings.port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,  # Railway terminates HTTPS in front of the app
        forwarded_allow_ips="*",
        log_level="info",
    )
