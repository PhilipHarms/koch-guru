"""Turn a recipe URL into a draft that can be saved to Notion.

Most recipe sites embed schema.org/Recipe data as JSON-LD (for Google's recipe
snippets). That is read deterministically. Only if a page has none, the page
text goes to the model. The model also picks tags, but only from the existing
tag options in Notion.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol, TypeVar
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
MAX_PAGE_BYTES = 5_000_000
MAX_PAGE_TEXT = 40_000
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 KochGuru/1.0"
)

T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    async def structured(self, *, system: str, messages: list[dict[str, Any]], output_type: type[T]) -> T: ...


class RecipeImportError(RuntimeError):
    """Raised with a user-facing message when a page cannot be imported."""


Photo = tuple[bytes, str]  # (image data, MIME type)
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_PHOTOS = 4


@dataclass
class IngredientLink:
    """An ingredient of the recipe to link in the ingredients database."""

    name: str  # exactly as in the database, or a new name
    emoji: str | None = None
    new: bool = False  # not in the database yet
    aisle: str | None = None  # supermarket aisle (tag) for a new ingredient


@dataclass
class RecipeDraft:
    name: str
    url: str = ""  # empty for recipes from photos
    ingredients: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    servings: str | None = None
    total_minutes: int | None = None
    image: str | None = None
    tags: list[str] = field(default_factory=list)
    icon: str | None = None  # emoji for the Notion page
    origin: list[str] = field(default_factory=list)  # cookbook, existing Notion options only
    photos: list[Photo] = field(default_factory=list, repr=False)  # attached to the Notion page
    source: str = "json-ld"  # "text" or "photo" when extracted by the model
    links: list[IngredientLink] = field(default_factory=list)  # set by `prepare_import`

    @property
    def site(self) -> str:
        return urlsplit(self.url).netloc.removeprefix("www.") if self.url else ""


# --- URLs ----------------------------------------------------------------------------

def find_url(text: str) -> str | None:
    match = URL_PATTERN.search(text or "")
    return match.group(0).rstrip(").,;!?") if match else None


def normalize_url(url: str) -> str:
    """For duplicate checks: no scheme, no www, no fragment, no trailing slash."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return urlunsplit(("", host, parts.path.rstrip("/"), parts.query, "")).lstrip("/")


async def fetch_page(url: str, http: httpx.AsyncClient) -> tuple[str, str]:
    """(final URL after redirects, HTML)."""
    try:
        response = await http.get(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "de,en;q=0.8",
        })
    except httpx.HTTPError as exc:
        raise RecipeImportError("Die Seite konnte ich nicht erreichen.") from exc
    if response.status_code >= 400:
        raise RecipeImportError(f"Die Seite hat mit Fehler {response.status_code} geantwortet.")
    if "html" not in response.headers.get("content-type", "html"):
        raise RecipeImportError("Unter dem Link ist keine Webseite, sondern eine Datei.")
    if len(response.content) > MAX_PAGE_BYTES:
        raise RecipeImportError("Die Seite ist zu groß.")
    return str(response.url), response.text


# --- Text helpers --------------------------------------------------------------------

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\r\f\v]+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")


def clean(text: Any) -> str:
    """Strip HTML tags and entities, collapse whitespace."""
    if text is None:
        return ""
    text = html.unescape(TAG_RE.sub(" ", str(text)))
    text = SPACE_RE.sub(" ", text).strip()
    return SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.meta: dict[str, str] = {}
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "meta":
            a = dict(attrs)
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta.setdefault(key.lower(), a["content"])
        elif tag in {"p", "li", "br", "h1", "h2", "h3", "h4", "tr", "div"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


META_IMAGES = ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src")


def meta_image(meta: dict[str, str], page_url: str) -> str | None:
    """The preview photo a page shows when its link is shared (og:image), as a full address."""
    for key in META_IMAGES:
        if meta.get(key):
            return _image(urljoin(page_url, html.unescape(meta[key].strip())))
    return None


def page_photo(page_html: str, page_url: str) -> str | None:
    return meta_image(page_text(page_html)[1], page_url)


def page_text(page_html: str) -> tuple[str, dict[str, str]]:
    """Readable text of a page (truncated) plus its meta tags."""
    parser = _TextExtractor()
    parser.feed(page_html)
    lines = (SPACE_RE.sub(" ", line).strip() for line in "".join(parser.parts).splitlines())
    text = "\n".join(line for line in lines if line)
    return text[:MAX_PAGE_TEXT], parser.meta


# --- schema.org / JSON-LD ------------------------------------------------------------

JSONLD_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)
DURATION_RE = re.compile(
    r"^P(?:(?P<d>\d+(?:\.\d+)?)D)?(?:T(?:(?P<h>\d+(?:\.\d+)?)H)?(?:(?P<m>\d+(?:\.\d+)?)M)?(?:\d+(?:\.\d+)?S)?)?$",
    re.IGNORECASE,
)


def parse_duration(value: Any) -> int | None:
    """ISO 8601 duration like PT1H30M -> minutes."""
    if not isinstance(value, str):
        return None
    match = DURATION_RE.match(value.strip())
    if not match or not any(match.groupdict().values()):
        return None
    d, h, m = (float(match.group(k) or 0) for k in ("d", "h", "m"))
    minutes = round(d * 1440 + h * 60 + m)
    return minutes or None


def _is_recipe(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.split("/")[-1].lower() == "recipe" for k in kinds)


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def find_jsonld_recipe(page_html: str) -> dict[str, Any] | None:
    for block in JSONLD_RE.findall(page_html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            # Some sites put raw newlines or trailing commas into JSON-LD.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", block.strip().replace("\n", " ")))
            except json.JSONDecodeError:
                continue
        for node in _walk(data):
            if _is_recipe(node):
                return node
    return None


def _steps(instructions: Any) -> list[str]:
    if instructions is None:
        return []
    if isinstance(instructions, str):
        text = html.unescape(instructions)
        parts = re.split(r"<br\s*/?>|</p>|</li>|\n+", text, flags=re.IGNORECASE)
        return [s for s in (clean(p) for p in parts) if s]
    if isinstance(instructions, dict):
        if "itemListElement" in instructions:  # HowToSection
            return _steps(instructions["itemListElement"])
        return _steps(instructions.get("text") or instructions.get("name"))
    if isinstance(instructions, list):
        return [step for item in instructions for step in _steps(item)]
    return []


def secure_url(value: str) -> str | None:
    """An image address as https: "//cdn…" and "http://…" become https, which browsers load anyway."""
    value = value.strip()
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://"):
        return "https://" + value[len("http://"):]
    return value if value.startswith("https://") else None


def _image(value: Any) -> str | None:
    if isinstance(value, str):
        return secure_url(value)
    if isinstance(value, list):
        return next((img for v in value if (img := _image(v))), None)
    if isinstance(value, dict):
        return _image(value.get("url") or value.get("contentUrl"))
    return None


def _first_text(value: Any) -> str | None:
    if isinstance(value, list):
        value = next((v for v in value if v not in (None, "")), None)
    text = clean(value)
    return text or None


def draft_from_jsonld(data: dict[str, Any], url: str) -> RecipeDraft | None:
    name = clean(data.get("name") or data.get("headline"))
    ingredients = [clean(i) for i in (data.get("recipeIngredient") or data.get("ingredients") or [])]
    ingredients = [i for i in ingredients if i]
    if not name or not ingredients:
        return None
    total = parse_duration(data.get("totalTime"))
    if total is None:
        parts = [parse_duration(data.get(k)) for k in ("prepTime", "cookTime")]
        total = sum(p for p in parts if p) or None
    return RecipeDraft(
        name=name,
        url=url,
        ingredients=ingredients,
        steps=_steps(data.get("recipeInstructions")),
        servings=_first_text(data.get("recipeYield")),
        total_minutes=total,
        image=_image(data.get("image")),
    )


# --- Model-assisted parts ------------------------------------------------------------

EMOJI_FIELD = "Genau ein Emoji, das das Gericht gut darstellt"


class Classification(BaseModel):
    tags: list[str] = Field(description="Passende Tags, nur aus der vorgegebenen Liste")
    emoji: str = Field(description=EMOJI_FIELD)


class ExtractedRecipe(BaseModel):
    ist_rezept: bool = Field(description="false, wenn die Seite kein Rezept enthält")
    name: str = Field(description="Name des Rezepts wie auf der Seite")
    zutaten: list[str] = Field(description="Zutaten mit Mengen, eine pro Eintrag")
    schritte: list[str] = Field(description="Zubereitungsschritte in Reihenfolge")
    portionen: str = Field(description="Portionen oder leer")
    minuten: int = Field(description="Gesamtzeit in Minuten oder 0, wenn unbekannt")
    tags: list[str] = Field(description="Passende Tags, nur aus der vorgegebenen Liste")
    emoji: str = Field(description=EMOJI_FIELD)


TAG_RULES = (
    "Wähle passende Tags NUR aus dieser Liste, exakt so geschrieben: {options}. "
    "Nimm nur Tags, die eindeutig zutreffen, zum Beispiel Ernährungsform, Gerichtart, Küche "
    "oder Saison. Lieber zu wenige als falsche. Ist die Liste leer, gib keine Tags zurück. "
    "Wähle außerdem genau ein Emoji als Icon, das das Gericht möglichst konkret zeigt, zum Beispiel "
    "🍝 Pasta, 🍛 Curry, 🥗 Salat, 🍲 Eintopf oder Suppe, 🍕 Pizza, 🌮 Tacos, 🍜 Nudelsuppe, "
    "🥘 Pfannengericht, 🍰 Kuchen. Nur ein einzelnes Emoji, kein Text."
)

FALLBACK_ICON = "🍽️"


def clean_emoji(value: str | None) -> str | None:
    """A single emoji or None. Rejects text, so Notion never gets an invalid icon."""
    value = (value or "").strip()
    if not value or len(value) > 8 or any(ch.isascii() and not ch.isspace() for ch in value):
        return None
    if any(ch.isspace() for ch in value):
        return None
    return value


async def classify(draft: RecipeDraft, options: list[str], llm: StructuredLLM) -> None:
    """Set tags (existing options only) and an emoji icon on the draft."""
    summary = f"Rezept: {draft.name}\nZutaten: {'; '.join(draft.ingredients)}"
    choice = await llm.structured(
        system="Du ordnest Rezepte in eine private Rezeptsammlung ein. "
        + TAG_RULES.format(options=", ".join(options)),
        messages=[{"role": "user", "content": summary}],
        output_type=Classification,
    )
    draft.tags = filter_tags(choice.tags, options)
    draft.icon = clean_emoji(choice.emoji) or FALLBACK_ICON


def filter_tags(tags: list[str], options: list[str]) -> list[str]:
    by_key = {o.casefold(): o for o in options}
    result: list[str] = []
    for tag in tags:
        option = by_key.get(tag.strip().casefold())
        if option and option not in result:
            result.append(option)
    return result


async def extract_with_llm(url: str, page_html: str, options: list[str], llm: StructuredLLM) -> RecipeDraft:
    text, meta = page_text(page_html)
    if len(text) < 200:
        raise RecipeImportError(
            "Auf der Seite finde ich kaum Text. Seiten, die ihren Inhalt erst per JavaScript laden "
            "(zum Beispiel Instagram oder TikTok), kann ich nicht lesen."
        )
    result = await llm.structured(
        system=(
            "Du liest Rezepte aus Webseiten aus. Übernimm Name, Zutaten und Schritte so, wie sie "
            "auf der Seite stehen, ohne etwas zu erfinden oder zu übersetzen. "
            + TAG_RULES.format(options=", ".join(options))
        ),
        messages=[{"role": "user", "content": f"URL: {url}\n\n<seite>\n{text}\n</seite>"}],
        output_type=ExtractedRecipe,
    )
    if not result.ist_rezept or not result.name.strip() or not result.zutaten:
        raise RecipeImportError("Auf der Seite habe ich kein Rezept gefunden.")
    return RecipeDraft(
        name=result.name.strip(),
        url=url,
        ingredients=[i.strip() for i in result.zutaten if i.strip()],
        steps=[s.strip() for s in result.schritte if s.strip()],
        servings=result.portionen.strip() or None,
        total_minutes=result.minuten or None,
        image=meta_image(meta, url),
        tags=filter_tags(result.tags, options),
        icon=clean_emoji(result.emoji) or FALLBACK_ICON,
        source="text",
    )


async def import_from_url(
    url: str, http: httpx.AsyncClient, llm: StructuredLLM, tag_options: list[str]
) -> RecipeDraft:
    final_url, page_html = await fetch_page(url, http)
    data = find_jsonld_recipe(page_html)
    draft = draft_from_jsonld(data, final_url) if data else None
    if draft is None:
        log.info("Kein JSON-LD-Rezept auf %s, lese Seitentext mit dem Modell.", final_url)
        return await extract_with_llm(final_url, page_html, tag_options, llm)
    draft.image = draft.image or page_photo(page_html, final_url)
    await classify(draft, tag_options, llm)
    return draft


# --- Photos --------------------------------------------------------------------------

class PhotoRecipe(ExtractedRecipe):
    quelle: str = Field(
        description="Kochbuch aus der vorgegebenen Liste, wenn eindeutig erkennbar, sonst leer"
    )


PHOTO_PROMPT = (
    "Du liest Rezepte von Fotos ab: Kochbuchseiten, Zeitschriften, Screenshots oder handschriftliche "
    "Rezepte. Mehrere Fotos gehören zum selben Rezept. Übernimm Name, Zutaten mit Mengen und die Schritte "
    "so, wie sie dort stehen, ohne zu übersetzen oder etwas zu ergänzen. Unleserliche Stellen markierst "
    "du mit [?]. "
)
ORIGIN_RULE = (
    "Quelle: Wenn auf dem Foto oder in der Bildunterschrift eindeutig erkennbar ist, aus welchem dieser "
    "Kochbücher das Rezept stammt, gib den Namen exakt so zurück: {options}. Sonst lass das Feld leer."
)


def photo_content(photos: list[Photo], caption: str) -> list[dict[str, Any]]:
    text = "Lies das Rezept von diesen Fotos ab."
    if caption.strip():
        text += f"\nBildunterschrift: {caption.strip()}"
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for data, mime in photos:
        encoded = base64.b64encode(data).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}})
    return parts


async def import_from_photos(
    photos: list[Photo],
    caption: str,
    llm: StructuredLLM,
    tag_options: list[str],
    origin_options: list[str],
) -> RecipeDraft:
    photos = [p for p in photos if p[1] in PHOTO_TYPES][:MAX_PHOTOS]
    if not photos:
        raise RecipeImportError("Das Bildformat kann ich nicht lesen. Schick es bitte als Foto.")
    system = PHOTO_PROMPT + TAG_RULES.format(options=", ".join(tag_options))
    if origin_options:
        system += " " + ORIGIN_RULE.format(options=", ".join(origin_options))
    result = await llm.structured(
        system=system,
        messages=[{"role": "user", "content": photo_content(photos, caption)}],
        output_type=PhotoRecipe,
    )
    if not result.ist_rezept or not result.name.strip() or not result.zutaten:
        raise RecipeImportError("Auf dem Foto habe ich kein Rezept erkannt.")
    return RecipeDraft(
        name=result.name.strip(),
        ingredients=[i.strip() for i in result.zutaten if i.strip()],
        steps=[s.strip() for s in result.schritte if s.strip()],
        servings=result.portionen.strip() or None,
        total_minutes=result.minuten or None,
        tags=filter_tags(result.tags, tag_options),
        icon=clean_emoji(result.emoji) or FALLBACK_ICON,
        origin=filter_tags([result.quelle], origin_options) if result.quelle else [],
        photos=photos,
        source="photo",
    )
