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
    ingredient_ids: tuple[str, ...] = ()  # Notion page ids, in the same order as `ingredients`
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


@dataclass(frozen=True)
class Ingredient:
    """A page of the ingredients database, as the shopping list needs it."""

    id: str  # Notion page id
    name: str
    icon: str | None = None  # emoji, or image address of a Notion icon
    bought: bool = False  # "Bought": in the house, ticked off on the shopping list
    bought_on: str | None = None  # "Gekauft am", ISO date of the last tick
    extra: bool = False  # own item without a recipe, e.g. washing-up liquid
    aisle: str | None = None  # supermarket aisle from the ingredient's tags, e.g. "Milchprodukt"
