"""Settings from environment variables (.env locally, service variables on Railway).

The variable names TELEGRAM_TOKEN, NOTION_TOKEN and NOTION_DATABASE_ID are the
ones already configured on Railway and must not be renamed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "anthropic/claude-sonnet-5.5"  # OpenRouter model slug


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class PropertyNames:
    """Preferred Notion property names. Missing ones are skipped or auto-detected."""

    link: str = "Link"
    tags: str = "Tags"
    origin: str = "Origin"
    ingredients: str = "Ingredients"  # text/select property or relation to an ingredients DB
    this_week: str = "This Week?"  # checkbox


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    notion_token: str
    notion_database_id: str
    openrouter_api_key: str
    model: str = DEFAULT_MODEL
    allowed_user_ids: frozenset[int] = frozenset()
    properties: PropertyNames = PropertyNames()
    recipe_cache_seconds: int = 300


def _parse_user_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError as exc:
            raise ConfigError(
                f"ALLOWED_USER_IDS enthält keinen gültigen Telegram-User-ID-Wert: {part!r}"
            ) from exc
    return frozenset(ids)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """Read and validate settings. Pass `env` to bypass os.environ (used in tests)."""
    if env is None:
        load_dotenv()
        env = dict(os.environ)

    def get(name: str, default: str = "") -> str:
        return env.get(name, default).strip()

    required = ["TELEGRAM_TOKEN", "NOTION_TOKEN", "NOTION_DATABASE_ID", "OPENROUTER_API_KEY"]
    missing = [name for name in required if not get(name)]
    if missing:
        message = "Fehlende Umgebungsvariablen: " + ", ".join(missing)
        if "OPENROUTER_API_KEY" in missing and get("ANTHROPIC_API_KEY"):
            message += " (ANTHROPIC_API_KEY ist gesetzt: bitte in OPENROUTER_API_KEY umbenennen)"
        raise ConfigError(message)

    try:
        cache_seconds = int(get("RECIPE_CACHE_SECONDS", "300"))
    except ValueError as exc:
        raise ConfigError("RECIPE_CACHE_SECONDS muss eine ganze Zahl sein") from exc

    defaults = PropertyNames()
    return Settings(
        telegram_token=get("TELEGRAM_TOKEN"),
        notion_token=get("NOTION_TOKEN"),
        notion_database_id=get("NOTION_DATABASE_ID"),
        openrouter_api_key=get("OPENROUTER_API_KEY"),
        model=get("OPENROUTER_MODEL", DEFAULT_MODEL),
        allowed_user_ids=_parse_user_ids(get("ALLOWED_USER_IDS")),
        properties=PropertyNames(
            link=get("NOTION_PROP_LINK", defaults.link),
            tags=get("NOTION_PROP_TAGS", defaults.tags),
            origin=get("NOTION_PROP_ORIGIN", defaults.origin),
            ingredients=get("NOTION_PROP_INGREDIENTS", defaults.ingredients),
            this_week=get("NOTION_PROP_THIS_WEEK", defaults.this_week),
        ),
        recipe_cache_seconds=cache_seconds,
    )
