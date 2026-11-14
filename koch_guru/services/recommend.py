"""Recipe recommendations: Claude picks numbers from the catalog, the code does the rest.

Claude only returns catalog numbers plus a short reason. Numbers are validated
against the catalog, so the bot can never suggest a recipe that is not in Notion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, TypeVar

from pydantic import BaseModel, Field

from koch_guru.models import Recipe

MAX_SUGGESTIONS = 4

MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def season(day: date) -> str:
    return {12: "Winter", 1: "Winter", 2: "Winter",
            3: "Frühling", 4: "Frühling", 5: "Frühling",
            6: "Sommer", 7: "Sommer", 8: "Sommer"}.get(day.month, "Herbst")


SYSTEM_PROMPT = """\
Du bist KochGuru, der Küchenassistent eines privaten Haushalts. Du bekommst die \
komplette Rezeptsammlung des Haushalts als nummerierte Liste und eine Nachricht \
mit Wünschen, Einschränkungen oder vorhandenen Zutaten.

Deine Aufgabe: Wähle passende Rezepte AUSSCHLIESSLICH aus dieser Liste aus.

Regeln:
- Höchstens 4 Rezepte. Weniger ist in Ordnung, wenn nicht mehr wirklich passen. \
Gar keins ist auch in Ordnung.
- Einschränkungen (z. B. vegetarisch, ohne Fleisch, schnell, leicht) gelten strikt. \
Wenn Name und Tags nicht eindeutig zeigen, dass ein Rezept passt, lass es weg.
- Nennt die Nachricht vorhandene Zutaten, bevorzuge Rezepte, die sie verwenden.
- Ohne konkreten Wunsch: wähle eine abwechslungsreiche Mischung, die zur Jahreszeit passt.
- Verwende nur Nummern, die in der Liste stehen. Erfinde keine Rezepte.

Antwortstil: Deutsch, locker, kurz.
- `antwort`: ein bis zwei Sätze an den Haushalt. Wenn nichts passt, sag das ehrlich \
und kurz warum.
- `grund` pro Rezept: ein knapper Halbsatz, warum es passt.
"""


class Pick(BaseModel):
    nr: int = Field(description="Nummer des Rezepts aus der Liste")
    grund: str = Field(description="Knapper Halbsatz, warum das Rezept passt")


class Selection(BaseModel):
    antwort: str = Field(description="Ein bis zwei Sätze an den Haushalt")
    rezepte: list[Pick] = Field(description="Höchstens 4 ausgewählte Rezepte, beste zuerst")


T = TypeVar("T", bound=BaseModel)


class StructuredLLM(Protocol):
    async def structured(self, *, system: str, user: str, output_type: type[T]) -> T: ...


@dataclass(frozen=True)
class Suggestion:
    recipe: Recipe
    reason: str


@dataclass(frozen=True)
class Recommendation:
    message: str
    suggestions: list[Suggestion]


def build_catalog(recipes: list[Recipe]) -> str:
    lines = []
    for nr, recipe in enumerate(recipes, start=1):
        line = f"[{nr}] {recipe.name}"
        if recipe.tags:
            line += f" | Tags: {', '.join(recipe.tags)}"
        if recipe.ingredients:
            line += f" | Zutaten: {'; '.join(recipe.ingredients)}"
        lines.append(line)
    return "\n".join(lines)


def build_user_prompt(wish: str, recipes: list[Recipe], today: date) -> str:
    return (
        f"Heute ist der {today.day}. {MONTHS[today.month - 1]} {today.year} ({season(today)}).\n\n"
        f"<rezeptsammlung>\n{build_catalog(recipes)}\n</rezeptsammlung>\n\n"
        f"<nachricht>\n{wish}\n</nachricht>"
    )


def to_recommendation(selection: Selection, recipes: list[Recipe]) -> Recommendation:
    """Keep only valid, unique catalog numbers, at most MAX_SUGGESTIONS."""
    suggestions: list[Suggestion] = []
    seen: set[int] = set()
    for pick in selection.rezepte:
        if pick.nr in seen or not 1 <= pick.nr <= len(recipes):
            continue
        seen.add(pick.nr)
        suggestions.append(Suggestion(recipe=recipes[pick.nr - 1], reason=pick.grund.strip()))
        if len(suggestions) == MAX_SUGGESTIONS:
            break
    return Recommendation(message=selection.antwort.strip(), suggestions=suggestions)


async def recommend(
    wish: str,
    recipes: list[Recipe],
    llm: StructuredLLM,
    today: date | None = None,
) -> Recommendation:
    if not recipes:
        return Recommendation(
            message="Deine Rezeptsammlung in Notion ist leer, ich habe nichts zum Vorschlagen.",
            suggestions=[],
        )
    selection = await llm.structured(
        system=SYSTEM_PROMPT,
        user=build_user_prompt(wish, recipes, today or date.today()),
        output_type=Selection,
    )
    return to_recommendation(selection, recipes)
