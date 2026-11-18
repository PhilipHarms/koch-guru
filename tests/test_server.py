"""The combined server starts core and bot together and stops them in reverse order."""

from fastapi.testclient import TestClient

from koch_guru import server
from koch_guru.config import load_settings


def test_lifespan_starts_and_stops_core_and_bot(monkeypatch):
    calls = []

    class FakeCore:
        repo = object()
        http = None

        async def start(self):
            calls.append("core.start")

        async def aclose(self):
            calls.append("core.close")

    async def start_bot(bot):
        calls.append("bot.start")

    async def stop_bot(bot):
        calls.append("bot.stop")

    monkeypatch.setattr(server, "build_core", lambda settings: FakeCore())
    monkeypatch.setattr(server, "build_application", lambda settings, core: "bot")
    monkeypatch.setattr(server, "start_bot", start_bot)
    monkeypatch.setattr(server, "stop_bot", stop_bot)

    settings = load_settings({
        "TELEGRAM_TOKEN": "1:x", "NOTION_TOKEN": "n", "NOTION_DATABASE_ID": "db",
        "OPENROUTER_API_KEY": "k", "APP_USERS": "philip:" + "k" * 30,
    })
    with TestClient(server.build_server_app(settings)) as client:
        assert client.get("/healthz").status_code == 200
        assert calls == ["core.start", "bot.start"]
    assert calls == ["core.start", "bot.start", "bot.stop", "core.close"]
