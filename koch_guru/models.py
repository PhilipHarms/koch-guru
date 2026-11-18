"""Domain model shared by the Notion layer, the services and the bot."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recipe:
    id: str  # Notion page id
    name: str
    notion_url: str
    url: str | None = None  # external recipe link, if any
    tags: tuple[str, ...] = ()
    origin: tuple[str, ...] = ()  # cookbook or source
    ingredients: tuple[str, ...] = ()
    this_week: bool = False  # on the "This Week?" list
    emoji: str | None = None  # page icon, shown when there is no photo
    created: str | None = None  # ISO timestamp of the Notion page, for "newest first"
    cover: str | None = None  # cover image URL; Notion-hosted ones expire after an hour

    @property
    def short_id(self) -> str:
        """Page id without dashes, short enough for Telegram callback data."""
        return self.id.replace("-", "")

    @property
    def link(self) -> str:
        """Best link to open the recipe: the external source if usable, else the Notion page."""
        if self.url and self.url.startswith(("http://", "https://")):
            return self.url
        return self.notion_url
