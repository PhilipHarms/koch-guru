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
    ingredients: tuple[str, ...] = ()

    @property
    def link(self) -> str:
        """Best link to open the recipe: the external source if usable, else the Notion page."""
        if self.url and self.url.startswith(("http://", "https://")):
            return self.url
        return self.notion_url
