from datetime import date

from koch_guru.models import Recipe
from koch_guru.services.recommend import (
    Pick,
    Selection,
    build_catalog,
    build_user_prompt,
    recommend,
    to_recommendation,
)

RECIPES = [
    Recipe(id=f"p{i}", name=n, notion_url=f"https://www.notion.so/p{i}", tags=t, ingredients=z)
    for i, (n, t, z) in enumerate([
        ("Brokkoli-Pasta", ("Nudeln", "Vegetarisch"), ("Brokkoli", "Feta")),
        ("Chili con Carne", ("Fleisch",), ()),
        ("Linsencurry", ("Curry", "Vegan"), ()),
        ("Kürbissuppe", ("Suppe", "Vegetarisch"), ()),
        ("Ramen", ("Japanisch",), ()),
    ])
]


class FakeLLM:
    def __init__(self, selection):
        self.selection = selection
        self.calls = []

    async def structured(self, *, system, user, output_type):
        self.calls.append({"system": system, "user": user, "output_type": output_type})
        return self.selection


def test_catalog_is_numbered_from_one():
    catalog = build_catalog(RECIPES)
    assert catalog.splitlines()[0] == "[1] Brokkoli-Pasta | Tags: Nudeln, Vegetarisch | Zutaten: Brokkoli; Feta"
    assert catalog.splitlines()[1] == "[2] Chili con Carne | Tags: Fleisch"


def test_prompt_has_german_date_and_season():
    prompt = build_user_prompt("was Warmes", RECIPES, date(2026, 11, 14))
    assert "14. November 2026 (Herbst)" in prompt
    assert "<nachricht>\nwas Warmes\n</nachricht>" in prompt


def test_invalid_and_duplicate_numbers_are_dropped_and_capped():
    selection = Selection(antwort="Bitte schön", rezepte=[
        Pick(nr=1, grund="a"), Pick(nr=99, grund="erfunden"), Pick(nr=0, grund="x"),
        Pick(nr=1, grund="doppelt"), Pick(nr=3, grund="b"), Pick(nr=4, grund="c"),
        Pick(nr=5, grund="d"), Pick(nr=2, grund="e"),
    ])
    rec = to_recommendation(selection, RECIPES)
    assert [s.recipe.name for s in rec.suggestions] == ["Brokkoli-Pasta", "Linsencurry", "Kürbissuppe", "Ramen"]
    assert rec.suggestions[0].reason == "a"


async def test_recommend_passes_catalog_and_maps_result():
    llm = FakeLLM(Selection(antwort="Zwei vegetarische Ideen", rezepte=[Pick(nr=4, grund="wärmt"), Pick(nr=1, grund="Brokkoli weg")]))
    rec = await recommend("vegetarisch, wir haben Brokkoli", RECIPES, llm, today=date(2026, 11, 14))
    assert [s.recipe.id for s in rec.suggestions] == ["p3", "p0"]
    assert "[5] Ramen" in llm.calls[0]["user"]
    assert llm.calls[0]["output_type"] is Selection


async def test_empty_database_skips_llm():
    llm = FakeLLM(None)
    rec = await recommend("egal", [], llm)
    assert rec.suggestions == [] and "leer" in rec.message
    assert llm.calls == []
