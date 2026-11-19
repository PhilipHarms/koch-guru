"""Shopping list: ingredients of the recipes of the week, grouped by recipe, plus own items."""

import re

from koch_guru.models import Ingredient, Recipe
from koch_guru.services.shopping import amounts_from_content, shopping_list, today

DAL = Recipe(id="r-dal", name="Kürbis-Dal", notion_url="n", this_week=True,
             ingredients=("Kürbis", "Rote Linsen", "Tomaten"), ingredient_ids=("i-kuerbis", "i-linsen", "i-tomaten"))
SHAKSHUKA = Recipe(id="r-shak", name="Shakshuka", notion_url="n", this_week=True,
                   ingredients=("Tomaten", "Eier"), ingredient_ids=("i-tomaten", "i-eier"))
PASTA = Recipe(id="r-pasta", name="Pasta", notion_url="n", ingredients=("Nudeln",), ingredient_ids=("i-nudeln",))

INGREDIENTS = {i.id: i for i in [
    Ingredient("i-kuerbis", "Kürbis", icon="🎃"),
    Ingredient("i-linsen", "Rote Linsen", bought=True, bought_on="2026-10-01"),
    Ingredient("i-tomaten", "Tomaten", icon="🍅"),
    Ingredient("i-eier", "Eier"),
    Ingredient("i-nudeln", "Nudeln"),
    Ingredient("i-spueli", "Spülmittel", extra=True),
    Ingredient("i-rolle", "Küchenrolle", extra=True, bought=True, bought_on="2026-11-18"),
    Ingredient("i-alt", "Alufolie", extra=True, bought=True, bought_on="2026-11-10"),
]}


def build(recipes=(DAL, SHAKSHUKA, PASTA), amounts=None):
    return shopping_list(recipes, INGREDIENTS, amounts or {}, today="2026-11-18", can_check=True, can_add=True)


def test_groups_per_recipe_of_the_week_with_shared_ingredients_noted():
    result = build(amounts={"r-dal": {"Kürbis": "1", "Tomaten": "400 g"}})
    assert [g["recipe_id"] for g in result["groups"]] == ["r-dal", "r-shak"]  # Pasta is not planned
    dal = [(i["name"], i["amount"], i["done"], i["also"]) for i in result["groups"][0]["items"]]
    assert dal == [
        ("Kürbis", "1", False, []),
        ("Rote Linsen", None, True, []),  # bought before: shown ticked, can be put back
        ("Tomaten", "400 g", False, ["Shakshuka"]),
    ]
    shak = [(i["name"], i["also"]) for i in result["groups"][1]["items"]]
    assert shak == [("Tomaten", ["Kürbis-Dal"]), ("Eier", [])]
    assert result["groups"][0]["items"][0]["icon"] == "🎃"


def test_open_items_are_counted_once():
    assert build()["open"] == 4  # Kürbis, Tomaten, Eier, Spülmittel


def test_own_items_stay_visible_on_the_day_they_were_ticked():
    extras = [(i["name"], i["done"]) for i in build()["extras"]]
    assert extras == [("Küchenrolle", True), ("Spülmittel", False)]  # Alufolie was bought last week


def test_own_item_that_a_recipe_needs_is_shown_with_the_recipe_only():
    ingredients = INGREDIENTS | {"i-eier": Ingredient("i-eier", "Eier", extra=True)}
    result = shopping_list([SHAKSHUKA], ingredients, {}, today="2026-11-18", can_check=True, can_add=True)
    assert "Eier" not in [i["name"] for i in result["extras"]]


def test_empty_week():
    result = build(recipes=(PASTA,))
    assert result["groups"] == [] and result["open"] == 1  # only Spülmittel


def test_amounts_come_from_the_ingredient_lines_of_the_page():
    content = {"ingredients": [
        {"group": "Für die Salsa"},
        {"name": "Hokkaido-Kürbis", "amount": "1"},
        {"name": "rote Linsen", "amount": "200 g"},
        {"name": "Kreuzkümmel", "amount": None},
        {"name": "Kürbiskerne", "amount": "2 EL"},  # a second line must not overwrite the first
    ]}
    assert amounts_from_content(content, ["Kürbis", "Rote Linsen", "Salz"]) == {"Kürbis": "1", "Rote Linsen": "200 g"}


def test_today_is_a_date():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", today())
