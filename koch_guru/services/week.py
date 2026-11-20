"""Plan the week: Claude picks a varied set of recipes from the collection.

Like recommend.py, the model only returns catalog numbers; the code keeps the valid ones.
Recipes already on the week list, cooked in the last two weeks or shown before are left out
of the catalog, so the model cannot pick them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field

from koch_guru.models import Recipe
from koch_guru.services.recommend import MONTHS, StructuredLLM, build_catalog, season

WEEK_SIZE = 5
REST_DAYS = 14

WEEK_PROMPT = """\
Du planst für einen privaten Haushalt die Gerichte der kommenden Woche. Unten steht ihre \
Rezeptsammlung als nummerierte Liste, dazu was schon auf der Wochenliste steht.

Wähle genau {count} Rezepte AUSSCHLIESSLICH aus der Liste.

Regeln:
- Abwechslung über die Woche: verschiedene Küchen und Hauptzutaten, nicht zweimal Pasta, \
nicht zweimal Curry. Bezieh die Gerichte mit ein, die schon auf der Wochenliste stehen oder \
schon ausgewählt sind.
- {quick_rule}
- Passend zur Jahreszeit.
- Gut bewertete Rezepte („Sterne“) bevorzugen. Ein Rezept, das lange nicht gekocht wurde \
oder neu ist (Tag „New“), darf dabei sein.
- Gekocht wird an normalen Abenden: keine Desserts, Beilagen, Soßen oder reinen Snacks, \
außer die Sammlung hat sonst zu wenig.
- Verwende nur Nummern, die in der Liste stehen. Erfinde keine Rezepte.

Antwort auf Deutsch:
- `grund` pro Rezept: ein knapper Halbsatz, warum es in die Woche passt. Den Namen nicht wiederholen.
- `schnell`: true, wenn das Rezept schnell gemacht ist (Tag „Quick“ oder „Schnell“, oder \
erkennbar unter etwa 30 Minuten).
"""


class WeekPick(BaseModel):
    nr: int = Field(description="Nummer des Rezepts aus der Liste")
    grund: str = Field(description="Knapper Halbsatz, warum es in die Woche passt")
    schnell: bool = Field(description="true, wenn das Rezept schnell gemacht ist")


class WeekPlan(BaseModel):
    rezepte: list[WeekPick] = Field(description="Die ausgewählten Rezepte, in einer sinnvollen Reihenfolge")


@dataclass(frozen=True)
class WeekSuggestion:
    recipe: Recipe
    reason: str
    quick: bool


def _recently_cooked(recipe: Recipe, today: date) -> bool:
    if not recipe.last_cooked:
        return False
    try:
        return 0 <= (today - date.fromisoformat(recipe.last_cooked)).days < REST_DAYS
    except ValueError:
        return False


def _is_quick(recipe: Recipe) -> bool:
    return any(word in tag.casefold() for tag in recipe.tags for word in ("quick", "schnell"))


async def plan_week(
    recipes: list[Recipe],
    llm: StructuredLLM,
    *,
    today: date,
    count: int = WEEK_SIZE,
    keep: list[Recipe] | None = None,
    exclude_ids: set[str] | None = None,
) -> list[WeekSuggestion]:
    """`count` new suggestions. `keep` are suggestions the household already ticked; with them
    the week should still have one or two quick dishes. `exclude_ids` were shown before."""
    keep = keep or []
    skip = {r.id for r in keep} | (exclude_ids or set())
    planned = [r for r in recipes if r.this_week]
    catalog = [
        r for r in recipes
        if not r.this_week and r.id not in skip and not _recently_cooked(r, today)
    ]
    if not catalog or count <= 0:
        return []

    quick_kept = sum(_is_quick(r) for r in keep + planned)
    quick_rule = {
        0: "Ein bis zwei der Rezepte sind schnell gemacht (Tag „Quick“ oder „Schnell“, oder erkennbar "
           "unter etwa 30 Minuten).",
        1: "Ein schnelles Gericht ist schon dabei; ein zweites ist erlaubt, aber nicht nötig.",
    }.get(quick_kept, "Schnelle Gerichte sind schon genug dabei.")
    context = []
    if planned:
        context.append("Steht schon auf der Wochenliste: " + ", ".join(r.name for r in planned))
    if keep:
        context.append("Schon ausgewählt: " + ", ".join(r.name for r in keep))
    system = (
        WEEK_PROMPT.format(count=count, quick_rule=quick_rule)
        + f"\nHeute ist der {today.day}. {MONTHS[today.month - 1]} {today.year} ({season(today)}).\n\n"
        + ("\n".join(context) + "\n\n" if context else "")
        + f"<rezeptsammlung>\n{build_catalog(catalog, today)}\n</rezeptsammlung>"
    )
    plan = await llm.structured(
        system=system,
        messages=[{"role": "user", "content": f"Plan bitte {count} Gerichte für die Woche."}],
        output_type=WeekPlan,
    )
    suggestions: list[WeekSuggestion] = []
    seen: set[int] = set()
    for pick in plan.rezepte:
        if pick.nr in seen or not 1 <= pick.nr <= len(catalog):
            continue
        seen.add(pick.nr)
        recipe = catalog[pick.nr - 1]
        suggestions.append(WeekSuggestion(recipe, pick.grund.strip(), pick.schnell or _is_quick(recipe)))
        if len(suggestions) == count:
            break
    return suggestions
