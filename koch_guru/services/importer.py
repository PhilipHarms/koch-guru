"""Turn a recipe URL into a draft that can be saved to Notion.

Most recipe sites embed schema.org/Recipe data as JSON-LD (for Google's recipe
snippets). That is read deterministically. Only if a page has none, the page
text goes to the model. The model also picks tags, but only from the existing
tag options in Notion.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Protocol, TypeVar
from urllib.parse import urlsplit, urlunsplit

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
    async def structured(self, *, system: str, messages: list[dict[str, str]], output_type: type[T]) -> T: ...


class RecipeImportError(RuntimeError):
    """Raised with a user-facing message when a page cannot be imported."""


@dataclass
class RecipeDraft:
    name: str
    url: str
    ingredients: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    servings: str | None = None
    total_minutes: int | None = None
    image: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "json-ld"  # or "text" when extracted by the model

    @property
    def site(self) -> str:
        return urlsplit(self.url).netloc.removeprefix("www.")


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
        response = await http.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "de,en;q=0.8"})
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


def _image(value: Any) -> str | None:
    if isinstance(value, str):
        return value if value.startswith("http") else None
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

class TagChoice(BaseModel):
    tags: list[str] = Field(description="Passende Tags, nur aus der vorgegebenen Liste")


class ExtractedRecipe(BaseModel):
    ist_rezept: bool = Field(description="false, wenn die Seite kein Rezept enthält")
    name: str = Field(description="Name des Rezepts wie auf der Seite")
    zutaten: list[str] = Field(description="Zutaten mit Mengen, eine pro Eintrag")
    schritte: list[str] = Field(description="Zubereitungsschritte in Reihenfolge")
    portionen: str = Field(description="Portionen oder leer")
    minuten: int = Field(description="Gesamtzeit in Minuten oder 0, wenn unbekannt")
    tags: list[str] = Field(description="Passende Tags, nur aus der vorgegebenen Liste")


TAG_RULES = (
    "Wähle passende Tags NUR aus dieser Liste, exakt so geschrieben: {options}. "
    "Nimm nur Tags, die eindeutig zutreffen, zum Beispiel Ernährungsform, Gerichtart, Küche "
    "oder Saison. Lieber zu wenige als falsche. Ist die Liste leer, gib keine Tags zurück."
)


async def choose_tags(draft: RecipeDraft, options: list[str], llm: StructuredLLM) -> list[str]:
    if not options:
        return []
    summary = f"Rezept: {draft.name}\nZutaten: {'; '.join(draft.ingredients)}"
    choice = await llm.structured(
        system="Du ordnest Rezepte in eine private Rezeptsammlung ein. "
        + TAG_RULES.format(options=", ".join(options)),
        messages=[{"role": "user", "content": summary}],
        output_type=TagChoice,
    )
    return filter_tags(choice.tags, options)


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
        image=_image(meta.get("og:image")),
        tags=filter_tags(result.tags, options),
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
    draft.tags = await choose_tags(draft, tag_options, llm)
    return draft
