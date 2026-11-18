"""Recipe page content from Notion blocks: ingredients, steps and everything else.

Pages the bot creates have a fixed shape: an info line, "Zutaten", "Zubereitung" and
"Originalfoto". Pages written by hand or clipped from the web can look like anything, so
ingredient and step sections are found by their headings and the rest is passed on as
simple blocks the web app can show.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

INGREDIENT_WORDS = ("zutaten", "zutat", "ingredients", "ingredient")
STEP_WORDS = (
    "zubereitung", "anleitung", "schritte", "instructions", "method", "directions", "preparation",
)
HEADINGS = {"heading_1": 1, "heading_2": 2, "heading_3": 3}
TEXT_ITEMS = {"paragraph", "bulleted_list_item", "numbered_list_item", "to_do"}

UNITS = (
    r"kg|g|mg|ml|cl|dl|l|el|tl|msp|bund|prisen?|stück|stk|dosen?|becher|zehen?|scheiben?|handvoll"
    r"|pck|päckchen|packungen?|gläser|glas|tassen?|cups?|tbsp|tsp|oz|lbs?|cm|blätter|blatt|zweige?"
)
AMOUNT = re.compile(
    rf"^((?:ca\.\s*)?[\d½¼¾⅓⅔⅛][\d½¼¾⅓⅔⅛.,/\-–\s]*(?:\s*(?:{UNITS})\b\.?)?)\s+(\S.*)$",
    re.IGNORECASE,
)
MINUTES = re.compile(r"⏱️?\s*(\d+)\s*min", re.IGNORECASE)
SERVINGS = re.compile(r"🍽️?\s*([^·]+?)\s*(?:·|$)")


def fold(value: str) -> str:
    """Lower case without accents, so "Kürbis" and "kurbis" compare equal."""
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _words(value: str) -> list[str]:
    return [w for w in re.split(r"[^\w]+", fold(value)) if w]


def _rich(parts: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    runs = []
    for part in parts or []:
        text = part.get("plain_text") or ""
        if not text:
            continue
        run: dict[str, Any] = {"text": text}
        if part.get("href"):
            run["href"] = part["href"]
        annotations = part.get("annotations") or {}
        if annotations.get("bold"):
            run["bold"] = True
        if annotations.get("italic"):
            run["italic"] = True
        runs.append(run)
    return runs


def _plain(block: dict[str, Any]) -> str:
    data = block.get(block.get("type", "")) or {}
    return "".join(p.get("plain_text", "") for p in data.get("rich_text") or []).strip()


def _file_url(data: dict[str, Any]) -> str | None:
    kind = data.get("type")
    return (data.get(kind) or {}).get("url") if kind in ("external", "file") else None


# --- Generic blocks ------------------------------------------------------------------


def simple_blocks(blocks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Notion blocks as a short list of types the web app knows. Unknown types are left out."""
    out: list[dict[str, Any]] = []
    for block in blocks:
        out.extend(_simple(block))
    return out


def _simple(block: dict[str, Any]) -> list[dict[str, Any]]:
    kind = block.get("type", "")
    data = block.get(kind) or {}
    children = block.get("children") or []
    text = _rich(data.get("rich_text"))

    if kind in HEADINGS:
        return [{"type": "heading", "level": HEADINGS[kind], "text": text}] if text else []
    if kind == "paragraph":
        return [{"type": "paragraph", "text": text}] if text else []
    if kind in ("bulleted_list_item", "numbered_list_item"):
        item = {"type": "bullet" if kind == "bulleted_list_item" else "number", "text": text}
        if children:
            item["children"] = simple_blocks(children)
        return [item]
    if kind == "to_do":
        return [{"type": "todo", "text": text, "checked": bool(data.get("checked"))}]
    if kind in ("toggle", "quote", "callout"):
        item = {"type": kind, "text": text}
        if kind == "callout":
            icon = data.get("icon") or {}
            item["emoji"] = icon.get("emoji") if icon.get("type") == "emoji" else None
        if children:
            item["children"] = simple_blocks(children)
        return [item]
    if kind == "divider":
        return [{"type": "divider"}]
    if kind == "image":
        url = _file_url(data)
        caption = "".join(p.get("plain_text", "") for p in data.get("caption") or [])
        return [{"type": "image", "url": url, "caption": caption}] if url else []
    if kind in ("bookmark", "embed", "link_preview", "video"):
        url = data.get("url") or _file_url(data)
        caption = "".join(p.get("plain_text", "") for p in data.get("caption") or [])
        return [{"type": "link", "url": url, "caption": caption}] if url else []
    if kind in ("column_list", "column", "synced_block"):
        return simple_blocks(children)
    return []


# --- Ingredients ---------------------------------------------------------------------


def _clean_name(name: str) -> str:
    """"Mehl 405" and "Tomaten (Dose)" should still find "500 g Mehl" and "Tomaten"."""
    return re.sub(r"\s*[\d(].*$", "", name).strip() or name


def _mentions(words: list[str], text: str, name: str) -> bool:
    if " " in name:
        return name in text
    for word in words:
        at = word.rfind(name)
        # The name itself with a short ending (Tomate/Tomaten) or the end of a compound
        # (Kirschtomaten), but short names like "Ei" only on their own.
        if at >= 0 and len(word) - at - len(name) <= 2 and (at == 0 or len(name) >= 4):
            return True
    return False


class EmojiFinder:
    """Picks the emoji of the ingredient a free-text line talks about."""

    def __init__(self, preferred: Iterable[str], emoji_by_name: Mapping[str, str]) -> None:
        self._candidates: list[tuple[str, str]] = []
        seen = set()
        for name in [*preferred, *emoji_by_name]:
            emoji = emoji_by_name.get(name)
            key = fold(_clean_name(name))
            if emoji and key and key not in seen:
                seen.add(key)
                self._candidates.append((key, emoji))
        self._preferred = {fold(_clean_name(n)) for n in preferred}

    def __call__(self, line: str) -> str | None:
        text, words = fold(line), _words(line)
        hits = [(key, emoji) for key, emoji in self._candidates if _mentions(words, text, key)]
        if not hits:
            return None
        # Ingredients of this recipe first, then the longest (most specific) name.
        hits.sort(key=lambda hit: (hit[0] in self._preferred, len(hit[0])), reverse=True)
        return hits[0][1]


def ingredient_line(line: str, find_emoji: EmojiFinder) -> dict[str, Any]:
    line = line.strip().lstrip("-•*–").strip()
    match = AMOUNT.match(line)
    amount, name = (match.group(1).strip(), match.group(2).strip()) if match else (None, line)
    return {"name": name, "amount": amount, "emoji": find_emoji(name)}


def _lines(block: dict[str, Any]) -> list[str]:
    """Text lines of a list item or paragraph, including nested items."""
    lines = [line.strip() for line in _plain(block).split("\n") if line.strip()]
    for child in block.get("children") or []:
        if child.get("type") in TEXT_ITEMS:
            lines.extend(_lines(child))
    return lines


# --- Whole page ----------------------------------------------------------------------


def _section(heading: str) -> str | None:
    words = _words(heading)
    if any(w in INGREDIENT_WORDS for w in words):
        return "ingredients"
    if any(w in STEP_WORDS for w in words):
        return "steps"
    return None


def _info_line(text: str) -> tuple[int | None, str | None] | None:
    """The bot's first line: "⏱ 45 Min · 🍽 4 · Quelle: …"."""
    minutes, servings = MINUTES.search(text), SERVINGS.search(text)
    if not (minutes or servings or text.startswith("Quelle:")):
        return None
    return (int(minutes.group(1)) if minutes else None, servings.group(1).strip() if servings else None)


def parse_content(
    blocks: list[dict[str, Any]],
    *,
    ingredients: Iterable[str] = (),
    emoji_by_name: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Split a recipe page into info, ingredients, steps and the remaining blocks.

    `ingredients` are the recipe's linked ingredients; they are shown when the page has
    no ingredient list of its own and help to pick emojis for free-text lines.
    """
    linked = list(ingredients)
    emoji_by_name = emoji_by_name or {}
    find_emoji = EmojiFinder(linked, emoji_by_name)

    minutes: int | None = None
    servings: str | None = None
    items: list[dict[str, Any]] = []
    steps: list[dict[str, str]] = []
    rest: list[dict[str, Any]] = []
    section: str | None = None
    has_ingredient_section = False

    for index, block in enumerate(blocks):
        kind = block.get("type")
        if kind in HEADINGS:
            text = _plain(block)
            found = _section(text)
            if found is None and section and kind == "heading_3" and text:
                # A sub-heading inside a section, like "Für den Teig".
                (items if section == "ingredients" else steps).append({"group": text.rstrip(":")})
                continue
            section = found
            has_ingredient_section = has_ingredient_section or section == "ingredients"
            if section is None:
                rest.extend(_simple(block))
            continue
        if index == 0 and kind == "paragraph" and (info := _info_line(_plain(block))):
            minutes, servings = info
            continue
        if section == "ingredients" and kind in TEXT_ITEMS:
            for line in _lines(block):
                if line.endswith(":") and not AMOUNT.match(line):
                    items.append({"group": line.rstrip(":").strip()})
                else:
                    items.append(ingredient_line(line, find_emoji))
            continue
        if section == "steps" and kind in TEXT_ITEMS:
            steps.extend({"text": line} for line in _lines(block))
            continue
        rest.extend(_simple(block))

    if not has_ingredient_section:
        items = [{"name": n, "amount": None, "emoji": emoji_by_name.get(n)} for n in linked]

    return {
        "minutes": minutes,
        "servings": servings,
        "ingredients": items,
        "steps": steps,
        "blocks": rest,
    }
