"""Fill a recipe page that has only a link, notes or a photo.

The recipe is read like an import in the bot: from the linked page's JSON-LD or text. If
there is no link, or it holds no recipe (Instagram, YouTube), the notes and photos on the
Notion page are read instead. A second model call then writes the ingredient
lines and steps in German and names the plain ingredient behind every line, so it can be
linked to the ingredients database. Nothing is written to Notion here; the app shows a
preview first, and saving is a separate step.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

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
    IngredientLink,
    Photo,
    RecipeDraft,
    RecipeImportError,
    StructuredLLM,
    clean_emoji,
    draft_from_jsonld,
    extract_with_llm,
    fetch_page,
    find_jsonld_recipe,
    page_photo,
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
7. Zwischenüberschriften in der Zutatenliste, etwa „Pineapple salsa“ oder „For the dressing“, bleiben eigene Zeilen, aber als Gruppe: `zeile` wie „Für die Ananas-Salsa:“, `gruppe` true, `zutat` und `emoji` leer, `immer_da` false. Bei allen anderen Zeilen ist `gruppe` false.
8. `abteilung`: die Abteilung im Supermarkt aus <abteilungen>, in der man die Zutat findet, exakt so geschrieben wie dort. Passt keine oder gibt es keine Liste, lass das Feld leer.
"""


class PreparedIngredient(BaseModel):
    zeile: str = Field(description="Zutatenzeile auf Deutsch, mit Menge")
    zutat: str = Field(description="Die eigentliche Zutat ohne Menge und Zubereitung")
    emoji: str = Field(description="Genau ein Emoji für die Zutat")
    immer_da: bool = Field(description="true für Salz, Pfeffer, Wasser und Ähnliches")
    gruppe: bool = Field(default=False, description="true für Zwischenüberschriften wie „Für die Salsa:“")
    abteilung: str = Field(default="", description="Abteilung im Supermarkt aus der Liste, oder leer")


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
    group: bool = False  # a heading like "Für die Salsa:", never linked
    aisle: str | None = None  # supermarket aisle for a new ingredient, from the tags in Notion
    unsure: bool = False  # no name from the model; offered, but not preselected

    @property
    def include(self) -> bool:
        """Preselected in the preview: everything except what is always at home."""
        return not self.group and not self.unsure and (self.linked or not self.staple)

    def as_json(self) -> dict[str, Any]:
        if self.group:
            return {"line": self.line, "amount": None, "name": self.line.rstrip(":").strip(), "zutat": "",
                    "emoji": None, "status": "group", "staple": False, "include": False}
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
            "aisle": self.aisle,
        }


@dataclass
class GeneratedRecipe:
    source: str  # the link, or "Foto"
    url: str | None
    ingredients: list[GeneratedIngredient] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    servings: str | None = None
    minutes: int | None = None
    image: str | None = None  # the recipe photo of the linked page, for the Notion cover

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "url": self.url,
            "image": self.image,
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
        draft.image = draft.image or page_photo(page_html, final_url)
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
    aisles: Sequence[str] = (),
) -> GeneratedRecipe:
    """German lines and steps, and the ingredient from the database behind every line."""
    request = (
        f"Rezept: {draft.name}\n\n<zutaten>\n" + "\n".join(draft.ingredients) + "\n</zutaten>\n\n"
        "<schritte>\n" + "\n".join(draft.steps) + "\n</schritte>\n\n"
        f"Portionen: {draft.servings or ''}\n\n"
        "<vorhandene_zutaten>\n" + "\n".join(known) + "\n</vorhandene_zutaten>"
    )
    if aisles:
        request += "\n\n<abteilungen>\n" + "\n".join(aisles) + "\n</abteilungen>"
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
        if item.gruppe:
            # The colon marks the line as a group label when the page is read again.
            items.append(GeneratedIngredient(line=line.rstrip(":").strip() + ":", zutat="", emoji=None,
                                             staple=False, existing=None, group=True))
            continue
        existing = best_match(zutat or line, known) if (zutat or line) else None
        items.append(GeneratedIngredient(
            line=line,
            zutat=zutat or line,
            emoji=clean_emoji(item.emoji),
            staple=item.immer_da,
            existing=existing,
            linked=bool(existing and fold(existing) in linked_keys),
            # Only an aisle that exists as a tag; existing ingredients keep theirs.
            aisle=item.abteilung.strip() if item.abteilung.strip() in aisles and not existing else None,
        ))
    return GeneratedRecipe(
        source=draft.url or "Foto",
        url=draft.url or None,
        ingredients=items,
        steps=[s.strip() for s in result.schritte if s.strip()] or draft.steps,
        servings=result.portionen.strip() or draft.servings,
        minutes=draft.total_minutes,
        image=draft.image if draft.image and draft.image.startswith("https://") else None,
    )


async def prepare_import(
    draft: RecipeDraft, llm: StructuredLLM, known: list[str], aisles: Sequence[str] = ()
) -> RecipeDraft:
    """For an import in the bot: German lines and steps, and the ingredients to link.

    Links follow the preselection of "Rezept generieren": everything except what is always
    at home. If the model fails, the draft stays as it was and nothing gets linked.
    """
    try:
        prepared = await prepare(draft, llm, known, linked=[], aisles=aisles)
    except Exception as exc:  # the import still works, only without links
        log.warning("Zutaten für den Import nicht aufbereitet: %r", exc)
        return draft
    seen: set[str] = set()
    links = []
    for item in prepared.ingredients:
        name = item.existing or item.zutat
        if not item.include or not name or fold(name) in seen:
            continue
        seen.add(fold(name))
        links.append(IngredientLink(name=name, emoji=item.emoji, new=item.existing is None, aisle=item.aisle))
    return dataclasses.replace(
        draft,
        ingredients=[i.line for i in prepared.ingredients],
        steps=prepared.steps,
        servings=prepared.servings,
        links=links,
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
    aisles: Sequence[str] = (),
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
    result = await prepare(draft, llm, known, linked, aisles)
    if draft.source in ("notes",):
        result.source, result.url, result.image = "Notizen", None, None
    return result


# --- Ingredients typed in the edit screen ----------------------------------------------

NAME_PROMPT = """\
Zu jeder Zutatenzeile aus einem Rezept nennst du die eigentliche Zutat, damit sie mit der \
Zutaten-Datenbank eines deutschen Haushalts verknüpft werden kann. Die Zeilen selbst änderst du nicht.

1. `zutat`: die Zutat ohne Menge, Größe und Zubereitung: aus „2 EL dunkle Sojasauce“ wird \
„Sojasauce“, aus „1 große Zwiebel, fein gehackt“ wird „Zwiebel“. Gibt es sie in <vorhandene_zutaten>, \
schreib sie exakt so wie dort. Sonst einen kurzen, üblichen deutschen Namen.
2. `emoji`: genau ein Emoji, das die Zutat zeigt.
3. `immer_da`: true für Dinge, die immer im Haus sind und nicht eingekauft werden (Salz, Pfeffer, Wasser).
4. `abteilung`: die Abteilung im Supermarkt aus <abteilungen>, exakt so geschrieben, oder leer.
Gib die Zeilen in derselben Reihenfolge zurück, `zeile` jeweils unverändert.
"""


class NamedIngredient(BaseModel):
    zeile: str = Field(description="Die Zeile, unverändert")
    zutat: str = Field(description="Die eigentliche Zutat ohne Menge und Zubereitung")
    emoji: str = Field(description="Genau ein Emoji für die Zutat")
    immer_da: bool = Field(description="true für Salz, Pfeffer, Wasser und Ähnliches")
    abteilung: str = Field(default="", description="Abteilung im Supermarkt aus der Liste, oder leer")


class NamedIngredients(BaseModel):
    zutaten: list[NamedIngredient]


def line_name(line: str) -> str:
    """The words after the amount: "200 g rote Linsen" -> "rote Linsen"."""
    match = AMOUNT.match(line)
    return (match.group(2) if match else line).strip()


ALWAYS_AT_HOME = {"salz", "pfeffer", "wasser", "salz und pfeffer", "meersalz"}


async def name_ingredients(
    lines: Sequence[str], llm: StructuredLLM | None, known: list[str], aisles: Sequence[str] = ()
) -> list[GeneratedIngredient]:
    """For new ingredient lines: which ingredient of the database each means, or a name for a new one.

    The model names them and says what is always at home. Without a model, or if it
    fails, lines are matched by their words; the rest stay unlinked (not preselected).
    """
    if not lines:
        return []
    named: list[NamedIngredient] = []
    if llm is not None:
        request = "<zeilen>\n" + "\n".join(lines) + "\n</zeilen>\n\n"
        request += "<vorhandene_zutaten>\n" + "\n".join(known) + "\n</vorhandene_zutaten>"
        if aisles:
            request += "\n\n<abteilungen>\n" + "\n".join(aisles) + "\n</abteilungen>"
        try:
            answer = await llm.structured(
                system=NAME_PROMPT, messages=[{"role": "user", "content": request}], output_type=NamedIngredients
            )
            named = answer.zutaten
        except Exception as exc:  # the lines are saved anyway, just matched by their words
            log.warning("Zutaten nicht benannt: %r", exc)
    by_line = {fold(n.zeile.strip()): n for n in named}
    items = []
    for index, line in enumerate(lines):
        item = by_line.get(fold(line.strip())) or (named[index] if len(named) == len(lines) else None)
        if item is not None and item.zutat.strip():
            zutat = item.zutat.strip()
            existing = best_match(zutat, known) or best_match(line_name(line), known)
            items.append(GeneratedIngredient(
                line=line, zutat=existing or zutat, emoji=clean_emoji(item.emoji), staple=item.immer_da,
                existing=existing,
                aisle=item.abteilung.strip() if item.abteilung.strip() in aisles and not existing else None,
            ))
            continue
        existing = best_match(line_name(line), known)
        if existing:
            staple = fold(" ".join(existing.split())) in ALWAYS_AT_HOME
            items.append(GeneratedIngredient(line=line, zutat=existing, emoji=None, staple=staple, existing=existing))
        else:
            items.append(GeneratedIngredient(
                line=line, zutat=line_name(line), emoji=None, staple=False, existing=None, unsure=True))
    return items
