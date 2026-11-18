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
    "zubereitung", "anleitung", "schritte", "instructions", "instruction", "method", "methods",
    "directions", "preparation", "steps",
)
HEADINGS = {"heading_1": 1, "heading_2": 2, "heading_3": 3}
TEXT_ITEMS = {"paragraph", "bulleted_list_item", "numbered_list_item", "to_do"}

UNITS = (
    r"kg|g|mg|ml|cl|dl|l|el|tl|msp|bund|prisen?|stück|stk|dosen?|becher|zehen?|scheiben?|handvoll"
    r"|pck|päckchen|packungen?|gläser|glas|tassen?|cm|blätter|blatt|zweige?"
    r"|fl\.? oz|cups?|tbsps?|tbs|tablespoons?|tsps?|teaspoons?|oz|ounces?|lbs?|pounds?|pints?"
    r"|pinch(?:es)?|bunch(?:es)?|tins?|cans?|cloves?|handfuls?|sprigs?|stalks?|slices?"
)
AMOUNT = re.compile(
    rf"^((?:ca\.\s*)?[\d½¼¾⅓⅔⅛][\d½¼¾⅓⅔⅛.,/\-–\s]*(?:[x×]\s*\d[\d.,]*\s*)?(?:\s*(?:{UNITS})\b\.?)?)"
    rf"\s+(\S.*)$",
    re.IGNORECASE,
)
# Pages without headings: lines like "Instructions:" start a section, numbered lines are steps.
MARKER_MAX_WORDS = 4
INGREDIENT_MAX_CHARS = 70
MIN_GUESSED_INGREDIENTS = 3
NUMBERING = re.compile(r"^\s*(?:\d+\s*[.)]|(?:schritt|step)\s*\d+\s*[:.)]?)(?:\s+|$)", re.IGNORECASE)
GROUP_START = re.compile(r"^(?:for|für)\b", re.IGNORECASE)
SERVES_LINE = re.compile(r"^(?:serves|makes|für|portionen:?)\s+(\d.*?)\.?$", re.IGNORECASE)
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


def image_urls(blocks: Iterable[dict[str, Any]]) -> list[str]:
    """Addresses of all photos on a page, nested ones included, in page order."""
    urls: list[str] = []
    for block in blocks:
        if block.get("type") == "image" and (url := _file_url(block.get("image") or {})):
            urls.append(url)
        urls.extend(image_urls(block.get("children") or []))
    return urls


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
        # The line has the shorter form: "Ei" for "Eier", "Zitrone" for "Zitronen".
        if len(word) >= 2 and name.startswith(word) and len(name) - len(word) <= 2:
            return True
    return False


def best_match(text: str, names: Iterable[str]) -> str | None:
    """The name from `names` that `text` means: the same word first, else the most specific mention.

    "Kirschtomaten" finds "Tomate", "Ei" finds "Eier", "Mehl" finds "Mehl 405".
    """
    folded, words = fold(text).strip(), _words(text)
    best: tuple[int, int, str] | None = None
    for name in names:
        key = fold(_clean_name(name))
        if not key:
            continue
        if key == folded or fold(name) == folded:
            rank = 2
        elif _mentions(words, folded, key):
            rank = 1
        else:
            continue
        if best is None or (rank, len(key)) > best[:2]:
            best = (rank, len(key), name)
    return best[2] if best else None


class IconFinder:
    """Picks the icon of the ingredient a free-text line talks about: an emoji or an image address."""

    def __init__(self, preferred: Iterable[str], icon_by_name: Mapping[str, str]) -> None:
        preferred = list(preferred)
        self._candidates: list[tuple[str, str]] = []
        seen = set()
        for name in [*preferred, *icon_by_name]:
            icon = icon_by_name.get(name)
            key = fold(_clean_name(name))
            if icon and key and key not in seen:
                seen.add(key)
                self._candidates.append((key, icon))
        self._preferred = {fold(_clean_name(n)) for n in preferred}

    def __call__(self, line: str) -> str | None:
        text, words = fold(line), _words(line)
        hits = [(key, emoji) for key, emoji in self._candidates if _mentions(words, text, key)]
        if not hits:
            return None
        # Ingredients of this recipe first, then the longest (most specific) name.
        hits.sort(key=lambda hit: (hit[0] in self._preferred, len(hit[0])), reverse=True)
        return hits[0][1]


# --- English amounts in German --------------------------------------------------------

# Unit words that only need a German name: (singular, plural).
UNIT_NAMES = {
    "tbsp": ("EL", "EL"), "tbsps": ("EL", "EL"), "tbs": ("EL", "EL"),
    "tablespoon": ("EL", "EL"), "tablespoons": ("EL", "EL"),
    "tsp": ("TL", "TL"), "tsps": ("TL", "TL"), "teaspoon": ("TL", "TL"), "teaspoons": ("TL", "TL"),
    "clove": ("Zehe", "Zehen"), "cloves": ("Zehe", "Zehen"),
    "bunch": ("Bund", "Bund"), "bunches": ("Bund", "Bund"),
    "pinch": ("Prise", "Prisen"), "pinches": ("Prise", "Prisen"),
    "tin": ("Dose", "Dosen"), "tins": ("Dose", "Dosen"), "can": ("Dose", "Dosen"), "cans": ("Dose", "Dosen"),
    "handful": ("Handvoll", "Handvoll"), "handfuls": ("Handvoll", "Handvoll"),
    "sprig": ("Zweig", "Zweige"), "sprigs": ("Zweig", "Zweige"),
    "stalk": ("Stange", "Stangen"), "stalks": ("Stange", "Stangen"),
    "slice": ("Scheibe", "Scheiben"), "slices": ("Scheibe", "Scheiben"),
    # German ones written in different ways: "El", "Tl.", "mL"
    "el": ("EL", "EL"), "tl": ("TL", "TL"), "ml": ("ml", "ml"),
}
# Units converted to metric: factor and German unit.
UNIT_FACTORS = {
    "cup": (240, "ml"), "cups": (240, "ml"),
    "oz": (28.35, "g"), "ounce": (28.35, "g"), "ounces": (28.35, "g"),
    "lb": (453.6, "g"), "lbs": (453.6, "g"), "pound": (453.6, "g"), "pounds": (453.6, "g"),
    "fl oz": (29.57, "ml"), "pint": (473, "ml"), "pints": (473, "ml"),
}
FRACTIONS = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
NUMBER = r"(?:\d+(?:[.,]\d+)?(?:\s+\d+/\d+|\s*[½¼¾⅓⅔⅛])?|\d+/\d+|[½¼¾⅓⅔⅛])"
ENGLISH_AMOUNT = re.compile(
    rf"^(?P<about>ca\.\s*)?(?P<low>{NUMBER})(?:\s*[-–]\s*(?P<high>{NUMBER}))?\s*(?P<unit>fl\.? oz|[a-z]+)\.?$",
    re.IGNORECASE,
)
FAHRENHEIT = re.compile(r"(\d{3})\s*(?:°\s*F\b|degrees\s+f(?:ahrenheit)?\b|F\b(?=\s*\(|\s*/|\s*or\b))", re.IGNORECASE)


def _number(text: str) -> float:
    text = text.strip().replace(",", ".")
    total = 0.0
    for part in re.findall(r"\d+/\d+|\d+(?:\.\d+)?|[½¼¾⅓⅔⅛]", text):
        if part in FRACTIONS:
            total += FRACTIONS[part]
        elif "/" in part:
            top, bottom = part.split("/")
            total += int(top) / int(bottom) if int(bottom) else 0
        else:
            total += float(part)
    return total


def _german_number(text: str) -> str:
    return text.strip().replace(".", ",")


def _rounded(value: float) -> str:
    step = 5 if value < 100 else 10
    return str(max(step, int(round(value / step) * step))) if value >= 2.5 else f"{value:.1f}".replace(".", ",")


def german_amount(amount: str) -> str:
    """ "2 tbsp" -> "2 EL", "1/2 cup" -> "120 ml", "8 oz" -> "230 g". Other amounts stay as they are."""
    match = ENGLISH_AMOUNT.match(amount.strip())
    if not match:
        return amount
    unit = re.sub(r"\s+", " ", match.group("unit").lower().replace(".", ""))
    low, high = match.group("low"), match.group("high")
    about = "ca. " if match.group("about") else ""
    if unit in UNIT_NAMES:
        singular, plural = UNIT_NAMES[unit]
        many = _number(high or low) > 1
        numbers = _german_number(low) + (f"–{_german_number(high)}" if high else "")
        return f"{about}{numbers} {plural if many else singular}"
    if unit in UNIT_FACTORS:
        factor, metric = UNIT_FACTORS[unit]
        numbers = _rounded(_number(low) * factor) + (f"–{_rounded(_number(high) * factor)}" if high else "")
        return f"{about}{numbers} {metric}"
    return amount


def german_temperatures(text: str) -> str:
    """ "Preheat the oven to 400°F" -> "Preheat the oven to 200 °C"."""
    if re.search(r"\d\s*°\s*C\b", text):  # "200°C/400°F" already has it in Celsius
        return text

    def celsius(match: re.Match[str]) -> str:
        value = (int(match.group(1)) - 32) * 5 / 9
        return f"{int(round(value / 10) * 10)} °C"

    return FAHRENHEIT.sub(celsius, text)


def ingredient_item(name: str, amount: str | None, icon: str | None) -> dict[str, Any]:
    """An ingredient for the app: emojis go in "emoji", Notion icons and images in "icon"."""
    item: dict[str, Any] = {"name": name, "amount": amount, "emoji": None}
    if icon and icon.startswith(("https://", "http://")):
        item["icon"] = icon
    else:
        item["emoji"] = icon
    return item


def ingredient_line(line: str, find_icon: IconFinder) -> dict[str, Any]:
    line = re.sub(r"^[^\w(½¼¾⅓⅔⅛]+", "", line.strip())  # list marks like "-", "•" or "▫️"
    match = AMOUNT.match(line)
    amount, name = (match.group(1).strip(), match.group(2).strip()) if match else (None, line)
    name = re.sub(r"^of\s+", "", name)  # "2 cloves of garlic"
    return ingredient_item(name, german_amount(amount) if amount else None, find_icon(name))


def _is_step(line: str) -> bool:
    """A sentence or a numbered line, as opposed to a short ingredient line."""
    return bool(NUMBERING.match(line)) or len(line) > 80 or (len(line) > 25 and line.endswith((".", "!")))


def _is_ingredient(line: str) -> bool:
    return not _is_step(line) and len(line) <= INGREDIENT_MAX_CHARS


def _is_group(line: str) -> bool:
    """A label inside the ingredients, like "Für die Soße:" or "For decoration"."""
    return not AMOUNT.match(line) and (line.endswith(":") or bool(GROUP_START.match(line)))


def _step_text(line: str) -> str:
    return german_temperatures(NUMBERING.sub("", line, count=1).strip())


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


def _marker(block: dict[str, Any]) -> str | None:
    """A heading or a short line that starts the ingredients or the steps ("Zutaten", "Instructions:")."""
    kind = block.get("type")
    if kind not in HEADINGS and kind != "paragraph":
        return None
    text = _plain(block).rstrip(":").strip()
    if not text or (kind == "paragraph" and len(text.split()) > MARKER_MAX_WORDS):
        return None
    return _section(text)


def _leading_ingredient_lines(blocks: list[dict[str, Any]], start: int) -> int:
    """How many ingredient-like lines follow from `start` before anything else."""
    count = 0
    for block in blocks[start:]:
        if block.get("type") not in TEXT_ITEMS:
            break
        lines = _lines(block)
        if not all(_is_ingredient(line) for line in lines):
            break
        count += len(lines)
    return count


def parse_content(
    blocks: list[dict[str, Any]],
    *,
    ingredients: Iterable[str] = (),
    icon_by_name: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Split a recipe page into info, ingredients, steps and the remaining blocks.

    Sections start at a heading or a short line such as "Zutaten" or "Instructions:". Many
    pages have neither: there a page that begins with a run of short lines gets those as
    ingredients, and the sentences right after them as steps.

    `ingredients` are the recipe's linked ingredients; they are shown when the page has
    no ingredient list of its own and help to pick icons for free-text lines.
    """
    linked = list(ingredients)
    icon_by_name = icon_by_name or {}
    find_icon = IconFinder(linked, icon_by_name)
    markers = [_marker(b) for b in blocks]
    has_ingredient_marker = "ingredients" in markers
    has_step_marker = "steps" in markers

    minutes: int | None = None
    servings: str | None = None
    items: list[dict[str, Any]] = []
    steps: list[dict[str, str]] = []
    rest: list[dict[str, Any]] = []
    section: str | None = None
    guess: str | None = None  # "ingredients" or "steps" while reading a page without headings; "off" after
    has_ingredient_list = False

    def add_ingredients(lines: list[str]) -> None:
        for line in lines:
            if _is_group(line):
                items.append({"group": line.rstrip(":").strip()})
            else:
                items.append(ingredient_line(line, find_icon))

    for index, block in enumerate(blocks):
        kind = block.get("type")
        if markers[index]:
            section, guess = markers[index], "off"
            has_ingredient_list = has_ingredient_list or section == "ingredients"
            continue
        if kind in HEADINGS:
            text = _plain(block)
            if section and kind == "heading_3" and text:
                # A sub-heading inside a section, like "Für den Teig".
                (items if section == "ingredients" else steps).append({"group": text.rstrip(":")})
                continue
            section, guess = None, "off"
            rest.extend(_simple(block))
            continue
        if index == 0 and kind == "paragraph" and (info := _info_line(_plain(block))):
            minutes, servings = info
            continue
        if kind == "paragraph" and servings is None and not (items or steps or rest):
            if serves := SERVES_LINE.match(_plain(block)):  # "Serves 2." or "Für 4 Personen"
                servings = serves.group(1).strip()
                continue
        if kind in TEXT_ITEMS and section == "ingredients":
            # A long line that starts with an amount is still an ingredient
            # ("600g mixed green veg, such as courgettes, fennel, …").
            lines = [line for line in _lines(block) if AMOUNT.match(line) or not _is_step(line)]
            if lines:
                add_ingredients(lines)
                continue
            # Sentences between the ingredients (an intro, a tip) are notes, not ingredients.
        elif kind in TEXT_ITEMS and section == "steps":
            lines = _lines(block)
            short_label = all(
                not _is_step(line) and not line.endswith(".") and len(line.split()) <= MARKER_MAX_WORDS
                for line in lines
            )
            if steps and short_label and not all(line.endswith(":") for line in lines):
                # "Tags", "ENJOY!", "Recipes you may like": the steps are over.
                section, guess = None, "off"
                rest.extend(_simple(block))
                continue
            for line in lines:
                if line.endswith(":") and not _is_step(line):
                    steps.append({"group": line.rstrip(":").strip()})
                elif text := _step_text(line):  # "Step 1." on its own line carries no text
                    steps.append({"text": text})
            continue
        if kind in TEXT_ITEMS and section is None and guess != "off":
            lines = _lines(block)
            if guess is None:
                # Only at the top of the page (photos may come first).
                at_top = all(b["type"] == "image" for b in rest)
                enough = _leading_ingredient_lines(blocks, index) >= MIN_GUESSED_INGREDIENTS
                guess = "ingredients" if at_top and enough and not has_ingredient_marker else "off"
            if guess == "ingredients":
                if all(_is_ingredient(line) for line in lines):
                    add_ingredients(lines)
                    has_ingredient_list = True
                    continue
                guess = "steps" if not has_step_marker else "off"
            if guess == "steps":
                if all(_is_step(line) for line in lines):
                    steps.extend({"text": text} for line in lines if (text := _step_text(line)))
                    continue
                guess = "off"
        rest.extend(_simple(block))

    if not has_ingredient_list:
        items = [ingredient_item(n, None, icon_by_name.get(n)) for n in linked]
    # A group label with nothing after it (e.g. "Top Tip" followed by prose) is dropped.
    while items and "group" in items[-1]:
        items.pop()
    while steps and "group" in steps[-1]:
        steps.pop()

    return {
        "minutes": minutes,
        "servings": servings,
        "ingredients": items,
        "steps": steps,
        "blocks": rest,
    }
