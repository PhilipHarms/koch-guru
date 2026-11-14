"""Bot wiring: access filter, handler flow and error handling, without network."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import Chat, Message, MessageEntity, Update, User
from telegram.constants import ParseMode

from koch_guru.bot import handlers
from koch_guru.bot.app import build_application
from koch_guru.config import load_settings
from koch_guru.models import Recipe
from koch_guru.services.recommend import Pick, Selection

PHILIP, STRANGER = 111, 999


def settings(allowed="111"):
    return load_settings({
        "TELEGRAM_TOKEN": "123456:TEST", "NOTION_TOKEN": "n", "NOTION_DATABASE_ID": "db",
        "ANTHROPIC_API_KEY": "a", "ALLOWED_USER_IDS": allowed,
    })


def update_from(user_id, text, edited=False):
    msg = Message(
        message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, first_name="T", is_bot=False), text=text,
        # Telegram marks commands with a bot_command entity; filters rely on it.
        entities=[MessageEntity(MessageEntity.BOT_COMMAND, 0, len(text.split()[0]))]
        if text.startswith("/") else None,
    )
    return Update(update_id=1, edited_message=msg) if edited else Update(update_id=1, message=msg)


def matching_callbacks(app, update):
    # Pretend getMe already ran, so command filters know the bot's username.
    app.bot._bot_user = User(id=123456, first_name="KochGuru", is_bot=True, username="kochguru_bot")
    update.set_bot(app.bot)
    update.effective_message.set_bot(app.bot)
    return [h.callback for h in app.handlers[0] if h.check_update(update)]


def test_routing_and_access_control():
    app = build_application(settings())
    assert matching_callbacks(app, update_from(PHILIP, "was vegetarisches"))[0] is handlers.suggest
    assert matching_callbacks(app, update_from(PHILIP, "/zufall"))[0] is handlers.random_recipes
    assert matching_callbacks(app, update_from(PHILIP, "/unbekannt"))[0] is handlers.unsupported
    assert matching_callbacks(app, update_from(STRANGER, "was vegetarisches")) == [handlers.not_allowed]
    assert matching_callbacks(app, update_from(STRANGER, "/zufall")) == [handlers.not_allowed]
    assert matching_callbacks(app, update_from(PHILIP, "edit", edited=True)) == []
    assert app.error_handlers


def test_empty_allowlist_locks_everyone_out():
    app = build_application(settings(allowed=""))
    assert matching_callbacks(app, update_from(PHILIP, "hallo")) == [handlers.not_allowed]


class FakeRepo:
    async def list_recipes(self, force_refresh=False):
        return [
            Recipe(id="a", name="Ramen", notion_url="https://www.notion.so/a"),
            Recipe(id="b", name="Käse & Spätzle", notion_url="https://www.notion.so/b", url="https://x.de/s"),
        ]


class FakeLLM:
    async def structured(self, *, system, user, output_type):
        return Selection(antwort="Heute was Deftiges?", rezepte=[Pick(nr=2, grund="macht satt")])


def fake_update(text):
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
    return SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=PHILIP)), message


def fake_context(error=None):
    return SimpleNamespace(bot_data={"services": handlers.Services(repo=FakeRepo(), llm=FakeLLM())}, error=error)


async def test_suggest_replies_with_escaped_html():
    update, message = fake_update("was Deftiges")
    await handlers.suggest(update, fake_context())
    message.chat.send_action.assert_awaited_once()
    text = message.reply_text.call_args.args[0]
    assert message.reply_text.call_args.kwargs["parse_mode"] == ParseMode.HTML
    assert '<a href="https://x.de/s">Käse &amp; Spätzle</a>' in text
    assert "<i>macht satt</i>" in text


async def test_error_handler_tells_the_user(monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply_text", reply)
    await handlers.on_error(update_from(PHILIP, "hallo"), fake_context(error=RuntimeError("boom")))
    assert "schiefgegangen" in reply.call_args.args[0]
