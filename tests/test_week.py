from datetime import date

from koch_guru.models import Recipe
from koch_guru.services.week import WeekPick, WeekPlan, plan_week

TODAY = date(2026, 11, 20)


def recipe(i, name, tags=(), **kw):
    return Recipe(id=f"r{i}", name=name, notion_url=f"https://notion.so/r{i}", tags=tuple(tags), **kw)


RECIPES = [
    recipe(1, "Kürbis-Dal", ["🥬 Veggie"]),
    recipe(2, "Pasta e ceci", ["🍝 Pasta", "⏱️ Quick"]),
    recipe(3, "Coq au vin", ["🐖 Fleisch"], this_week=True),
    recipe(4, "Shakshuka", ["⏱️ Quick"], last_cooked="2026-11-15"),
    recipe(5, "Lachs mit Miso", ["🐟 Fisch"], last_cooked="2026-10-01"),
    recipe(6, "Ramen", ["🍚 Asiatisch"]),
]


class FakeLLM:
    def __init__(self, picks):
        self.picks = picks
        self.system = ""

    async def structured(self, *, system, messages, output_type):
        assert output_type is WeekPlan
        self.system = system
        return WeekPlan(rezepte=[WeekPick(nr=n, grund=g, schnell=q) for n, g, q in self.picks])


async def test_plan_leaves_out_planned_recently_cooked_and_shown():
    llm = FakeLLM([(1, "wärmt", False), (2, "geht fix", False), (1, "doppelt", False), (9, "gibt es nicht", False)])
    result = await plan_week(RECIPES, llm, today=TODAY, count=3, exclude_ids={"r6"})
    catalog = llm.system.split("<rezeptsammlung>")[1]
    assert "Coq au vin" not in catalog and "Shakshuka" not in catalog and "Ramen" not in catalog
    assert "Lachs mit Miso" in catalog  # cooked seven weeks ago
    assert "Steht schon auf der Wochenliste: Coq au vin" in llm.system
    assert "Ein bis zwei der Rezepte sind schnell gemacht" in llm.system and "genau 3 Rezepte" in llm.system
    assert [(s.recipe.name, s.reason, s.quick) for s in result] == [
        ("Kürbis-Dal", "wärmt", False), ("Pasta e ceci", "geht fix", True),  # quick by its tag
    ]


async def test_kept_quick_dish_relaxes_the_rule():
    llm = FakeLLM([(1, "passt", False)])
    await plan_week(RECIPES, llm, today=TODAY, count=1, keep=[RECIPES[1]])
    assert "Schon ausgewählt: Pasta e ceci" in llm.system
    assert "Ein schnelles Gericht ist schon dabei" in llm.system
    assert "Pasta e ceci" not in llm.system.split("<rezeptsammlung>")[1]


async def test_nothing_left_to_plan():
    llm = FakeLLM([])
    assert await plan_week([RECIPES[2]], llm, today=TODAY) == []
    assert llm.system == ""  # no model call
