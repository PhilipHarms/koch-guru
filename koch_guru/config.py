"""Settings from environment variables (.env locally, service variables on Railway).

The variable names TELEGRAM_TOKEN, NOTION_TOKEN and NOTION_DATABASE_ID are the
ones already configured on Railway and must not be renamed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"
VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class ConfigError(RuntimeError):
    """Raised when required settings are missing or invalid."""


@dataclass(frozen=True)
class PropertyNames:
    """Preferred Notion property names. Missing ones are skipped or auto-detected."""

    link: str = "Link"
    tags: str = "Tags"
    ingredients: str = "Zutaten"


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    notion_token: str
    notion_database_id: str
    anthropic_api_key: str
    anthropic_model: str = DEFAULT_MODEL
    anthropic_effort: str = DEFAULT_EFFORT
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

    required = ["TELEGRAM_TOKEN", "NOTION_TOKEN", "NOTION_DATABASE_ID", "ANTHROPIC_API_KEY"]
    missing = [name for name in required if not get(name)]
    if missing:
        raise ConfigError("Fehlende Umgebungsvariablen: " + ", ".join(missing))

    effort = get("ANTHROPIC_EFFORT", DEFAULT_EFFORT).lower()
    if effort not in VALID_EFFORTS:
        raise ConfigError(
            f"ANTHROPIC_EFFORT muss einer von {sorted(VALID_EFFORTS)} sein, nicht {effort!r}"
        )

    try:
        cache_seconds = int(get("RECIPE_CACHE_SECONDS", "300"))
    except ValueError as exc:
        raise ConfigError("RECIPE_CACHE_SECONDS muss eine ganze Zahl sein") from exc

    defaults = PropertyNames()
    return Settings(
        telegram_token=get("TELEGRAM_TOKEN"),
        notion_token=get("NOTION_TOKEN"),
        notion_database_id=get("NOTION_DATABASE_ID"),
        anthropic_api_key=get("ANTHROPIC_API_KEY"),
        anthropic_model=get("ANTHROPIC_MODEL", DEFAULT_MODEL),
        anthropic_effort=effort,
        allowed_user_ids=_parse_user_ids(get("ALLOWED_USER_IDS")),
        properties=PropertyNames(
            link=get("NOTION_PROP_LINK", defaults.link),
            tags=get("NOTION_PROP_TAGS", defaults.tags),
            ingredients=get("NOTION_PROP_INGREDIENTS", defaults.ingredients),
        ),
        recipe_cache_seconds=cache_seconds,
    )
