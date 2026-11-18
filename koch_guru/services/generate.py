"""Fill a recipe page that has only a link, notes or a photo.

The recipe is read like an import in the bot: from the linked page's JSON-LD or text. If
there is no link, or it holds no recipe (Instagram, YouTube), the notes and photos on the
Notion page are read instead. A second model call then writes the ingredient
lines and steps in German and names the plain ingredient behind every line, so it can be
linked to the ingredients database. Nothing is written to Notion here; the app shows a
preview first, and saving is a separate step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field

from koch_guru.page_content import AMOUNT, best_match, fold, german_amount
from koch_guru.services.importer import (
    MAX_PHOTOS,
    PHOTO_TYPES,
    TAG_RULES,
    ExtractedRecipe,
    Photo,
    RecipeDraft,
    RecipeImportError,
    StructuredLLM,
    clean_emoji,
    draft_from_jsonld,
    extract_with_llm,
    fetch_page,
    find_jsonld_recipe,
    photo_content,
)

log = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 8_000_000
MIN_NOTES = 80  # characters of notes worth reading at all

NOTES_PROMPT = (
    "Du liest ein Rezept aus den Notizen einer Notion-Seite und, falls dabei, aus Fotos davon "
    "(Kochbuchseiten, Screenshots, handschriftliche Rezepte). Übernimm Name, Zutaten mit Mengen und "
    "die Schritte so, wie sie dort stehen, ohne etwas zu erfinden oder zu übersetzen. Stehen die Zutaten "
    "nur im Text der Schritte, liste sie mit ihren Mengen als Zutaten auf. Unleserliche Stellen markierst "
    "du mit [?]. Ist kein Rezept zu erkennen, setz ist_rezept auf false. "
)

PREPARE_PROMPT = """\
Du bereitest ein Rezept für die private Rezeptsammlung eines deutschen Haushalts auf.

1. Schreib jede Zutatenzeile auf Deutsch, mit deutschen Einheiten (EL, TL, g, ml, Prise, \
Bund, Zehe, Dose; Tassen und cups als ml, ounces und pounds als g). Ist sie schon deutsch, \
übernimm sie unverändert. Erfinde nichts dazu und lass nichts weg.
2. Nenne zu jeder Zeile die eigentliche Zutat, ohne Menge, Größe und Zubereitung: aus \
„2 EL dunkle Sojasauce“ wird „Sojasauce“, aus „1 große Zwiebel, fein gehackt“ wird \
„Zwiebel“. Gibt es die Zutat in der Liste der vorhandenen Zutaten, schreib sie exakt so \
wie dort. Sonst einen kurzen, üblichen deutschen Namen.
3. Wähle pro Zutat genau ein Emoji, das sie zeigt.
4. `immer_da` ist true für Dinge, die immer im Haus sind und nicht eingekauft werden: Salz, \
Pfeffer, Wasser und Ähnliches. Sonst false.
5. Schreib die Schritte auf Deutsch, in derselben Reihenfolge und ohne Inhalt zu ändern. \
Ofentemperaturen in °C.
6. `portionen` auf Deutsch, z. B. „4 Portionen“, oder leer.
"""


class PreparedIngredient(BaseModel):
    zeile: str = Field(description="Zutatenzeile auf Deutsch, mit Menge")
    zutat: str = Field(description="Die eigentliche Zutat ohne Menge und Zubereitung")
    emoji: str = Field(description="Genau ein Emoji für die Zutat")
    immer_da: bool = Field(description="true für Salz, Pfeffer, Wasser und Ähnliches")


class PreparedRecipe(BaseModel):
    zutaten: list[PreparedIngredient]
    schritte: list[str] = Field(description="Schritte auf Deutsch, in Reihenfolge")
    portionen: str = Field(description="Portionen auf Deutsch oder leer")


@dataclass
class GeneratedIngredient:
    line: str
    zutat: str
    emoji: str | None
    staple: bool
    existing: str | None  # name in the ingredients database, if there is one
    linked: bool = False  # already linked to this recipe

    @property
    def include(self) -> bool:
        """Preselected in the preview: everything except what is always at home."""
        return self.linked or not self.staple

    def as_json(self) -> dict[str, Any]:
        match = AMOUNT.match(self.line)
        return {
            "line": self.line,
            "amount": german_amount(match.group(1).strip()) if match else None,
            "name": match.group(2).strip() if match else self.line,
            "zutat": self.existing or self.zutat,
            "emoji": self.emoji,
            "status": "linked" if self.linked else "existing" if self.existing else "new",
            "staple": self.staple,
            "include": self.include,
        }


@dataclass
class GeneratedRecipe:
    source: str  # the link, or "Foto"
    url: str | None
    ingredients: list[GeneratedIngredient] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    servings: str | None = None
    minutes: int | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "servings": self.servings,
            "minutes": self.minutes,
            "ingredients": [i.as_json() for i in self.ingredients],
            "steps": self.steps,
        }


async def read_from_link(url: str, http: httpx.AsyncClient, llm: StructuredLLM) -> RecipeDraft:
    """JSON-LD if the site has it, else the page text through the model."""
    final_url, page_html = await fetch_page(url, http)
    data = find_jsonld_recipe(page_html)
    draft = draft_from_jsonld(data, final_url) if data else None
    if draft is not None:
        return draft
    return await extract_with_llm(final_url, page_html, [], llm)


async def read_from_notes(notes: str, photos: list[Photo], llm: StructuredLLM) -> RecipeDraft:
    """The recipe from the notes on the Notion page and the photos there."""
    content = photo_content(photos, "") if photos else [{"type": "text", "text": ""}]
    content[0] = {"type": "text", "text": f"Lies das Rezept aus diesen Notizen{' und Fotos' if photos else ''}.\n\n"
                  f"<notizen>\n{notes.strip()}\n</notizen>"}
    result = await llm.structured(
        system=NOTES_PROMPT + TAG_RULES.format(options=""),
        messages=[{"role": "user", "content": content}],
        output_type=ExtractedRecipe,
    )
    if not result.ist_rezept or not result.zutaten:
        raise RecipeImportError("In den Notizen und Fotos habe ich kein Rezept gefunden.")
    return RecipeDraft(
        name=result.name.strip(),
        ingredients=[i.strip() for i in result.zutaten if i.strip()],
        steps=[s.strip() for s in result.schritte if s.strip()],
        servings=result.portionen.strip() or None,
        total_minutes=result.minuten or None,
        source="notes",
    )


async def download_photos(urls: list[str], http: httpx.AsyncClient) -> list[Photo]:
    photos: list[Photo] = []
    for url in urls[:MAX_PHOTOS]:
        try:
            response = await http.get(url)
        except httpx.HTTPError as exc:
            log.warning("Foto aus Notion nicht geladen: %s", exc)
            continue
        mime = response.headers.get("content-type", "").split(";")[0].strip()
        if response.status_code == 200 and mime in PHOTO_TYPES and len(response.content) <= MAX_PHOTO_BYTES:
            photos.append((response.content, mime))
    return photos


async def prepare(
    draft: RecipeDraft,
    llm: StructuredLLM,
    known: list[str],
    linked: list[str],
) -> GeneratedRecipe:
    """German lines and steps, and the ingredient from the database behind every line."""
    request = (
        f"Rezept: {draft.name}\n\n<zutaten>\n" + "\n".join(draft.ingredients) + "\n</zutaten>\n\n"
        "<schritte>\n" + "\n".join(draft.steps) + "\n</schritte>\n\n"
        f"Portionen: {draft.servings or ''}\n\n"
        "<vorhandene_zutaten>\n" + "\n".join(known) + "\n</vorhandene_zutaten>"
    )
    result = await llm.structured(
        system=PREPARE_PROMPT,
        messages=[{"role": "user", "content": request}],
        output_type=PreparedRecipe,
    )
    linked_keys = {fold(n) for n in linked}
    items = []
    for item in result.zutaten:
        line, zutat = item.zeile.strip(), item.zutat.strip()
        if not line:
            continue
        existing = best_match(zutat or line, known) if (zutat or line) else None
        items.append(GeneratedIngredient(
            line=line,
            zutat=zutat or line,
            emoji=clean_emoji(item.emoji),
            staple=item.immer_da,
            existing=existing,
            linked=bool(existing and fold(existing) in linked_keys),
        ))
    return GeneratedRecipe(
        source=draft.url or "Foto",
        url=draft.url or None,
        ingredients=items,
        steps=[s.strip() for s in result.schritte if s.strip()] or draft.steps,
        servings=result.portionen.strip() or draft.servings,
        minutes=draft.total_minutes,
    )


async def generate(
    *,
    link: str | None,
    notes: str,
    photo_urls: list[str],
    http: httpx.AsyncClient,
    llm: StructuredLLM,
    known: list[str],
    linked: list[str],
) -> GeneratedRecipe:
    """Read the recipe from its link; if that gives nothing, from the notes and photos on the page."""
    draft: RecipeDraft | None = None
    problem: RecipeImportError | None = None
    if link:
        try:
            draft = await read_from_link(link, http, llm)
        except RecipeImportError as exc:
            problem = exc
            log.info("Link ohne Rezept (%s), versuche Notizen und Fotos.", exc)
    if draft is None:
        photos = await download_photos(photo_urls, http) if photo_urls else []
        if len(notes.strip()) >= MIN_NOTES or photos:
            draft = await read_from_notes(notes, photos, llm)
    if draft is None:
        raise problem or RecipeImportError(
            "Das Rezept hat weder einen Link noch Notizen oder Fotos, aus denen ich lesen könnte."
        )
    if not draft.ingredients:
        raise RecipeImportError("Im Rezept habe ich keine Zutaten gefunden.")
    result = await prepare(draft, llm, known, linked)
    if draft.source in ("notes",):
        result.source, result.url = "Notizen", None
    return result
