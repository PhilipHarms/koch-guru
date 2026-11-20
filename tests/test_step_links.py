import asyncio

import pytest

from koch_guru.services.step_links import StepLink, StepLinker, StepLinks, link_steps, recipe_text

QUESADILLAS = {
    "ingredients": [
        {"group": "Für die Füllung"},
        {"name": "Hüttenkäse", "amount": "250 g"},
        {"name": "Spinat", "amount": "100 g"},
        {"group": "Zum Braten"},
        {"name": "große Weizentortillas", "amount": "4"},
        {"name": "Öl", "amount": "1 EL"},
    ],
    "steps": [
        {"text": "Hüttenkäse und Spinat verrühren.", "uses": [1, 2]},
        {"group": "Braten"},
        {"text": "Die Füllung auf den Tortillas verteilen und zuklappen."},
        {"text": "In Öl braten, bis der Käse geschmolzen ist."},
    ],
}


class LinkLLM:
    def __init__(self, answer, delay=0.0):
        self.answer, self.delay, self.calls = answer, delay, 0

    async def structured(self, *, system, messages, output_type, max_tokens=None):
        assert output_type is StepLinks
        self.calls += 1
        self.text = messages[0]["content"]
        await asyncio.sleep(self.delay)
        return self.answer


def test_recipe_text_numbers_ingredients_and_steps_without_headings():
    text, numbers, count = recipe_text(QUESADILLAS)
    assert "[1] 250 g Hüttenkäse" in text and "[3] 4 große Weizentortillas" in text
    assert "Für die Füllung:" in text and "Braten:" in text
    assert "Schritt 3: In Öl braten" in text
    assert numbers == {1: 1, 2: 2, 3: 4, 4: 5} and count == 3


async def test_answer_is_mapped_to_ingredient_positions_and_checked():
    llm = LinkLLM(StepLinks(schritte=[
        StepLink(schritt=1, zutaten=[2, 1, 1]),
        StepLink(schritt=2, zutaten=[3, 99]),  # 99 is not on the list
        StepLink(schritt=3, zutaten=[4]),
        StepLink(schritt=7, zutaten=[1]),  # no step 7
    ]))
    assert await link_steps(QUESADILLAS, llm) == [[1, 2], [4], [5]]


async def test_no_question_without_steps_or_ingredients():
    llm = LinkLLM(StepLinks(schritte=[]))
    assert await link_steps({"ingredients": QUESADILLAS["ingredients"], "steps": []}, llm) == []
    assert await link_steps({"ingredients": [], "steps": [{"text": "Ofen vorheizen."}]}, llm) == [[]]
    assert llm.calls == 0


async def test_each_content_is_asked_once():
    llm = LinkLLM(StepLinks(schritte=[StepLink(schritt=1, zutaten=[1])]), delay=0.01)
    linker = StepLinker(llm)
    first, second = await asyncio.gather(linker.links(QUESADILLAS), linker.links(QUESADILLAS))
    assert first == second == [[1], [], []] and llm.calls == 1
    await linker.links(QUESADILLAS)
    assert llm.calls == 1
    changed = {**QUESADILLAS, "steps": [{"text": "Alles verrühren."}]}
    await linker.links(changed)
    assert llm.calls == 2


async def test_a_failed_answer_is_asked_again():
    class Failing(LinkLLM):
        async def structured(self, **kwargs):
            self.calls += 1
            raise RuntimeError("weg")

    llm = Failing(None)
    linker = StepLinker(llm)
    for _ in range(2):
        with pytest.raises(RuntimeError):
            await linker.links(QUESADILLAS)
    assert llm.calls == 2
