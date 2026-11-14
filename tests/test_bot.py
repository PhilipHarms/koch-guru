"""Bot wiring: access filter, handler flow and error handling, without network."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from telegram import CallbackQuery, Chat, Message, MessageEntity, PhotoSize, Update, User
from telegram.constants import ParseMode

from koch_guru.bot import handlers
from koch_guru.bot.app import build_application
from koch_guru.bot.render import week_keyboard
from koch_guru.config import load_settings
from koch_guru.models import Recipe
from koch_guru.services.conversation import ConversationStore
from koch_guru.services.importer import RecipeDraft, RecipeImportError
from koch_guru.services.recommend import Pick, Selection

PHILIP, STRANGER = 111, 999


def settings(allowed="111"):
    return load_settings({
        "TELEGRAM_TOKEN": "123456:TEST", "NOTION_TOKEN": "n", "NOTION_DATABASE_ID": "db",
        "OPENROUTER_API_KEY": "a", "ALLOWED_USER_IDS": allowed,
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


def photo_from(user_id):
    msg = Message(
        message_id=1, date=datetime.now(timezone.utc), chat=Chat(id=user_id, type="private"),
        from_user=User(id=user_id, first_name="T", is_bot=False),
        photo=[PhotoSize(file_id="f", file_unique_id="u", width=1280, height=960)],
    )
    return Update(update_id=3, message=msg)


def callback_from(user_id, data):
    query = CallbackQuery(id="q", from_user=User(id=user_id, first_name="T", is_bot=False),
                          chat_instance="c", data=data)
    return Update(update_id=2, callback_query=query)


def matching_callbacks(app, update):
    # Pretend getMe already ran, so command filters know the bot's username.
    app.bot._bot_user = User(id=123456, first_name="KochGuru", is_bot=True, username="kochguru_bot")
    update.set_bot(app.bot)
    if update.effective_message:
        update.effective_message.set_bot(app.bot)
    return [h.callback for h in app.handlers[0] if h.check_update(update)]


def test_routing_and_access_control():
    app = build_application(settings())
    assert matching_callbacks(app, update_from(PHILIP, "was vegetarisches"))[0] is handlers.suggest
    assert matching_callbacks(app, update_from(PHILIP, "das hier https://x.de/r"))[0] is handlers.import_link
    assert matching_callbacks(app, callback_from(PHILIP, "imp:save:abc")) == [handlers.import_decision]
    assert matching_callbacks(app, update_from(STRANGER, "https://x.de/r")) == [handlers.not_allowed]
    assert matching_callbacks(app, photo_from(PHILIP))[0] is handlers.photo_import
    assert matching_callbacks(app, photo_from(STRANGER)) == [handlers.not_allowed]
    assert matching_callbacks(app, update_from(PHILIP, "/zufall"))[0] is handlers.random_recipes
    assert matching_callbacks(app, update_from(PHILIP, "/woche"))[0] is handlers.week
    assert matching_callbacks(app, update_from(PHILIP, "/woche_leeren"))[0] is handlers.week_clear
    assert matching_callbacks(app, update_from(PHILIP, "/neu"))[0] is handlers.reset_conversation
    assert matching_callbacks(app, update_from(PHILIP, "/unbekannt"))[0] is handlers.unsupported
    assert matching_callbacks(app, callback_from(PHILIP, "cw:abc")) == [handlers.toggle_week]
    assert matching_callbacks(app, update_from(STRANGER, "was vegetarisches")) == [handlers.not_allowed]
    assert matching_callbacks(app, update_from(STRANGER, "/woche")) == [handlers.not_allowed]
    assert matching_callbacks(app, update_from(PHILIP, "edit", edited=True)) == []
    assert app.error_handlers


def test_empty_allowlist_locks_everyone_out():
    app = build_application(settings(allowed=""))
    assert matching_callbacks(app, update_from(PHILIP, "hallo")) == [handlers.not_allowed]


RAMEN = Recipe(id="aaaa-1", name="Ramen", notion_url="https://www.notion.so/a")
SPAETZLE = Recipe(id="bbbb-2", name="Käse & Spätzle", notion_url="https://www.notion.so/b",
                  url="https://x.de/s", this_week=True)


class FakeRepo:
    supports_this_week = True
    tag_options = ["Veggie", "Winter"]
    origin_options = ["Green Feast (Autumn Winter)"]

    def __init__(self, existing=(None, "")):
        self.updates = []
        self.cleared = False
        self.existing = existing
        self.created = []

    async def find_existing(self, draft):
        return self.existing

    async def create_recipe(self, draft):
        self.created.append(draft)
        return Recipe(id="neu-1", name=draft.name, notion_url="https://www.notion.so/neu1", url=draft.url)

    async def list_recipes(self, force_refresh=False):
        return [RAMEN, SPAETZLE]

    async def set_this_week(self, page_id, value):
        self.updates.append((page_id, value))

    async def clear_this_week(self):
        self.cleared = True
        return 1


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def structured(self, *, system, messages, output_type):
        self.calls.append(messages)
        return Selection(antwort="Heute was Deftiges?", rezepte=[Pick(nr=2, grund="macht satt")])


def fake_update(text, chat_id=PHILIP):
    message = SimpleNamespace(text=text, reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()))
    update = SimpleNamespace(
        effective_message=message, effective_user=SimpleNamespace(id=PHILIP),
        effective_chat=SimpleNamespace(id=chat_id), callback_query=None,
    )
    return update, message


def fake_context(svc=None, error=None):
    svc = svc or handlers.Services(repo=FakeRepo(), llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))
    return SimpleNamespace(bot_data={"services": svc}, error=error)


async def test_suggest_replies_with_html_and_week_buttons():
    update, message = fake_update("was Deftiges")
    await handlers.suggest(update, fake_context())
    message.chat.send_action.assert_awaited_once()
    text = message.reply_text.call_args.args[0]
    kwargs = message.reply_text.call_args.kwargs
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert '<a href="https://x.de/s">Käse &amp; Spätzle</a>' in text
    assert "<i>macht satt</i>" in text
    buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
    assert [(b.text, b.callback_data) for b in buttons] == [("✅ Käse & Spätzle", "cw:bbbb2")]


async def test_follow_up_sends_history_and_reset_clears_it():
    llm = FakeLLM()
    svc = handlers.Services(repo=FakeRepo(), llm=llm, conversations=ConversationStore(),
                            allowed_user_ids=frozenset({PHILIP}))
    await handlers.suggest(fake_update("was Deftiges")[0], fake_context(svc))
    await handlers.suggest(fake_update("lieber ohne Käse")[0], fake_context(svc))

    second = llm.calls[1]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert "Käse & Spätzle (macht satt)" in second[1]["content"]
    assert second[2]["content"] == "lieber ohne Käse"

    update, message = fake_update("/neu")
    await handlers.reset_conversation(update, fake_context(svc))
    assert svc.conversations.history(PHILIP) == []
    assert "von vorn" in message.reply_text.call_args.args[0]


async def test_week_and_week_clear():
    repo = FakeRepo()
    svc = handlers.Services(repo=repo, llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))
    update, message = fake_update("/woche")
    await handlers.week(update, fake_context(svc))
    assert "Käse &amp; Spätzle" in message.reply_text.call_args.args[0]
    assert "Ramen" not in message.reply_text.call_args.args[0]

    update, message = fake_update("/woche_leeren")
    await handlers.week_clear(update, fake_context(svc))
    assert repo.cleared and "1 Rezept von der Wochenliste" in message.reply_text.call_args.args[0]


def fake_callback(user_id, data, recipes):
    query = SimpleNamespace(
        data=data, answer=AsyncMock(), edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(reply_markup=week_keyboard(recipes)),
    )
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id)), query


async def test_toggle_week_button_adds_and_removes():
    repo = FakeRepo()
    svc = handlers.Services(repo=repo, llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))

    update, query = fake_callback(PHILIP, "cw:aaaa1", [RAMEN, SPAETZLE])
    await handlers.toggle_week(update, fake_context(svc))
    assert repo.updates == [("aaaa1", True)]
    assert "steht auf der Wochenliste" in query.answer.call_args.args[0]
    new_markup = query.edit_message_reply_markup.call_args.args[0]
    assert [b.text for row in new_markup.inline_keyboard for b in row] == ["✅ Ramen", "✅ Käse & Spätzle"]

    update, query = fake_callback(PHILIP, "cw:bbbb2", [RAMEN, SPAETZLE])
    await handlers.toggle_week(update, fake_context(svc))
    assert repo.updates[-1] == ("bbbb2", False)
    assert "runter" in query.answer.call_args.args[0]


async def test_toggle_week_rejects_strangers():
    repo = FakeRepo()
    svc = handlers.Services(repo=repo, llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))
    update, query = fake_callback(STRANGER, "cw:aaaa1", [RAMEN])
    await handlers.toggle_week(update, fake_context(svc))
    assert repo.updates == []
    assert "privat" in query.answer.call_args.args[0]


async def test_error_handler_tells_the_user(monkeypatch):
    reply = AsyncMock()
    monkeypatch.setattr(Message, "reply_text", reply)
    await handlers.on_error(update_from(PHILIP, "hallo"), fake_context(error=RuntimeError("boom")))
    assert "schiefgegangen" in reply.call_args.args[0]


async def test_error_handler_answers_button_presses(monkeypatch):
    answer = AsyncMock()
    monkeypatch.setattr(CallbackQuery, "answer", answer)
    await handlers.on_error(callback_from(PHILIP, "cw:x"), fake_context(error=RuntimeError("boom")))
    assert answer.call_args.kwargs["show_alert"] is True


def test_error_texts_point_to_the_cause():
    import httpx2
    import openai
    from notion_client import APIResponseError

    request = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")

    def status_error(cls, code):
        return cls("x", response=httpx2.Response(code, request=request), body=None)

    assert "OPENROUTER_API_KEY" in handlers.error_text(status_error(openai.AuthenticationError, 401))
    assert "Guthaben" in handlers.error_text(status_error(openai.APIStatusError, 402))
    assert "KI" in handlers.error_text(openai.APIConnectionError(request=request))
    assert "schiefgegangen" in handlers.error_text(ValueError())

    notion_403 = APIResponseError.__new__(APIResponseError)
    notion_403.code = "restricted_resource"
    assert "Update content" in handlers.error_text(notion_403)


DRAFT = RecipeDraft(name="Ofen-Süßkartoffeln <mit> Feta", url="https://example.com/r",
                    ingredients=["500 g Süßkartoffeln", "200 g Feta"], steps=["Backen."], tags=["Veggie"],
                    icon="🍠")


def import_services(monkeypatch, repo, result=DRAFT):
    async def fake_import(url, http, llm, tag_options):
        assert tag_options == ["Veggie", "Winter"]
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(handlers, "import_from_url", fake_import)
    return handlers.Services(repo=repo, llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))


def import_callback(user_id, data, text):
    query = SimpleNamespace(
        data=data, answer=AsyncMock(), edit_message_text=AsyncMock(), edit_message_reply_markup=AsyncMock(),
        message=SimpleNamespace(text=text),
    )
    return SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=user_id)), query


async def test_link_preview_then_save(monkeypatch):
    repo = FakeRepo()
    svc = import_services(monkeypatch, repo)
    update, message = fake_update("Probier mal https://example.com/r")
    await handlers.import_link(update, fake_context(svc))

    preview = message.reply_text.call_args.args[0]
    assert preview.startswith("🍠 <b>Ofen-Süßkartoffeln &lt;mit&gt; Feta</b>")
    assert "<b>Tags:</b> Veggie" in preview and "Soll ich das Rezept in Notion anlegen?" in preview
    buttons = [b for row in message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
    save, drop = (b.callback_data for b in buttons)
    assert save.startswith("imp:save:") and drop.startswith("imp:drop:")

    update, query = import_callback(PHILIP, save, preview)
    await handlers.import_decision(update, fake_context(svc))
    assert repo.created == [DRAFT]
    text = query.edit_message_text.call_args.args[0]
    assert "In Notion angelegt" in text and "Soll ich" not in text
    week = query.edit_message_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert week.callback_data == "cw:neu1"

    # A second press finds no draft anymore.
    update, query = import_callback(PHILIP, save, preview)
    await handlers.import_decision(update, fake_context(svc))
    assert len(repo.created) == 1
    assert "abgelaufen" in query.answer.call_args.args[0]


async def test_link_preview_then_discard(monkeypatch):
    repo = FakeRepo()
    svc = import_services(monkeypatch, repo)
    update, message = fake_update("https://example.com/r")
    await handlers.import_link(update, fake_context(svc))
    drop = message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][1].callback_data
    update, query = import_callback(PHILIP, drop, "")
    await handlers.import_decision(update, fake_context(svc))
    assert repo.created == []
    assert "Verworfen" in query.edit_message_text.call_args.args[0]


async def test_known_link_is_not_imported_again(monkeypatch):
    known = Recipe(id="k-1", name="Kenn ich", notion_url="https://www.notion.so/k1")
    repo = FakeRepo(existing=(known, "link"))
    svc = import_services(monkeypatch, repo)
    update, message = fake_update("https://example.com/r")
    await handlers.import_link(update, fake_context(svc))
    assert "schon in deiner Sammlung" in message.reply_text.call_args.args[0]
    assert message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == "cw:k1"


async def test_same_name_is_only_a_warning(monkeypatch):
    similar = Recipe(id="s-1", name="Ofen-Süßkartoffeln <mit> Feta", notion_url="https://www.notion.so/s1")
    svc = import_services(monkeypatch, FakeRepo(existing=(similar, "name")))
    update, message = fake_update("https://example.com/r")
    await handlers.import_link(update, fake_context(svc))
    assert "gibt es schon" in message.reply_text.call_args.args[0]
    assert message.reply_text.call_args.kwargs["reply_markup"] is not None


async def test_import_error_is_explained(monkeypatch):
    svc = import_services(monkeypatch, FakeRepo(), result=RecipeImportError("Die Seite hat mit Fehler 403 geantwortet."))
    update, message = fake_update("https://example.com/r")
    await handlers.import_link(update, fake_context(svc))
    assert "Fehler 403" in message.reply_text.call_args.args[0]


async def test_import_buttons_reject_strangers(monkeypatch):
    repo = FakeRepo()
    svc = import_services(monkeypatch, repo)
    update, query = import_callback(STRANGER, "imp:save:abc", "")
    await handlers.import_decision(update, fake_context(svc))
    assert repo.created == [] and "privat" in query.answer.call_args.args[0]


# --- Photos ----------------------------------------------------------------------------

def fake_photo_message(data=b"jpeg", caption=None, media_group_id=None, document=None):
    file = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    photo = [SimpleNamespace(get_file=AsyncMock())] if document is None else []
    if photo:
        photo[0].get_file.return_value = file
    if document is not None:
        document.get_file = AsyncMock(return_value=file)
    return SimpleNamespace(
        photo=photo, document=document, caption=caption, media_group_id=media_group_id,
        reply_text=AsyncMock(), chat=SimpleNamespace(send_action=AsyncMock()),
    )


def photo_update(message):
    return SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=PHILIP),
                           effective_chat=SimpleNamespace(id=PHILIP), callback_query=None)


PHOTO_DRAFT = RecipeDraft(name="Kürbis-Dal", ingredients=["1 Kürbis"], tags=["Veggie"], icon="🍛",
                          origin=["Green Feast (Autumn Winter)"], source="photo")


def photo_services(monkeypatch, repo, result=PHOTO_DRAFT):
    calls = []

    async def fake_import(photos, caption, llm, tag_options, origin_options):
        calls.append((photos, caption, origin_options))
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr(handlers, "import_from_photos", fake_import)
    svc = handlers.Services(repo=repo, llm=FakeLLM(), allowed_user_ids=frozenset({PHILIP}))
    return svc, calls


async def test_photo_shows_preview_and_saves(monkeypatch):
    repo = FakeRepo()
    svc, calls = photo_services(monkeypatch, repo)
    message = fake_photo_message(caption="aus Green Feast")
    await handlers.photo_import(photo_update(message), fake_context(svc))

    assert calls == [([(b"jpeg", "image/jpeg")], "aus Green Feast", ["Green Feast (Autumn Winter)"])]
    preview = message.reply_text.call_args.args[0]
    assert preview.startswith("🍛 <b>Kürbis-Dal</b>\n📷 Foto · 📚 Green Feast (Autumn Winter)")
    assert "Vom Foto gelesen" in preview
    save = message.reply_text.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data
    update, query = import_callback(PHILIP, save, preview)
    await handlers.import_decision(update, fake_context(svc))
    assert repo.created == [PHOTO_DRAFT]


async def test_album_is_read_as_one_recipe(monkeypatch):
    monkeypatch.setattr(handlers, "ALBUM_WAIT_SECONDS", 0.05)
    svc, calls = photo_services(monkeypatch, FakeRepo())
    first = fake_photo_message(b"seite-1", caption="Green Feast", media_group_id="g1")
    second = fake_photo_message(b"seite-2", media_group_id="g1")

    import asyncio
    task = asyncio.create_task(handlers.photo_import(photo_update(first), fake_context(svc)))
    await asyncio.sleep(0.01)
    await handlers.photo_import(photo_update(second), fake_context(svc))
    await task

    assert len(calls) == 1
    assert [p[0] for p in calls[0][0]] == [b"seite-1", b"seite-2"]
    assert calls[0][1] == "Green Feast"
    assert first.reply_text.await_count == 1 and second.reply_text.await_count == 0
    assert svc.albums == {}


async def test_image_document_is_accepted_and_errors_are_explained(monkeypatch):
    svc, calls = photo_services(monkeypatch, FakeRepo(), result=RecipeImportError("Auf dem Foto habe ich kein Rezept erkannt."))
    message = fake_photo_message(b"png", document=SimpleNamespace(mime_type="image/png"))
    await handlers.photo_import(photo_update(message), fake_context(svc))
    assert calls[0][0] == [(b"png", "image/png")]
    assert "kein Rezept erkannt" in message.reply_text.call_args.args[0]
