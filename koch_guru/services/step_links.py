"""Which ingredients each step uses, read by Claude, for the amounts next to a step in the cooking mode.

Word matching (`page_content.ingredients_in_step`) finds what a step *mentions*, which is often
not what it uses: "bis der Käse geschmolzen ist" names cheese that went in two steps earlier,
and "das Gemüse" names no ingredient at all. The model reads the whole method and says what
goes in at each step. As everywhere else, it answers with numbers only; the code keeps the
valid ones.

A recipe is read once per content: `StepLinker` keeps the answers, so the recipe page can ask
ahead and the cooking mode gets the same answer without waiting.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from typing import Any

from pydantic import BaseModel, Field

from koch_guru.services.recommend import StructuredLLM

LINKS_PROMPT = """\
Du bekommst ein Rezept: die Zutaten als nummerierte Liste und die Zubereitung als nummerierte \
Schritte. Gib für jeden Schritt an, welche Zutaten in diesem Schritt verarbeitet werden: \
hinzugefügt, geschnitten, vermischt, angebraten, darübergestreut. Also das, was man bei diesem \
Schritt in die Hand nimmt.

Regeln:
- Eine Zutat, die nur erwähnt wird, weil sie schon in einem früheren Schritt verarbeitet wurde, \
zählt nicht: „bis der Käse geschmolzen ist“, „die Zwiebeln weiter anbraten“, „die Füllung auf \
den Tortillas verteilen“ (die Tortillas zählen hier, die Zutaten der Füllung nicht).
- Sammelbegriffe auflösen: „das Gemüse“, „die Gewürze“, „die restlichen Zutaten“ meinen die \
passenden Zutaten der Liste, wenn sie in diesem Schritt dazukommen.
- Wird eine Zutat auf mehrere Schritte verteilt („die Hälfte der Butter“), gehört sie zu jedem \
dieser Schritte.
- Gibt es ähnliche Zutaten (zwei Käse, Öl zum Braten und Öl fürs Dressing), nimm die gemeinte. \
Überschriften wie „Für die Salsa:“ zeigen, wozu Zutaten und Schritte gehören.
- Schritte ohne Zutaten (Ofen vorheizen, servieren) bekommen eine leere Liste.
- Verwende nur Nummern aus der Zutatenliste.
"""

CACHE_SIZE = 300


class StepLink(BaseModel):
    schritt: int
    zutaten: list[int] = Field(default_factory=list)


class StepLinks(BaseModel):
    schritte: list[StepLink]


def recipe_text(content: dict[str, Any]) -> tuple[str, dict[int, int], int]:
    """The recipe as the model sees it, which ingredient number is which item, and the step count."""
    lines = ["Zutaten:"]
    numbers: dict[int, int] = {}
    for index, item in enumerate(content.get("ingredients") or []):
        if "group" in item:
            lines.append(f"{item['group']}:")
        elif item.get("name"):
            numbers[len(numbers) + 1] = index
            amount = f"{item['amount']} " if item.get("amount") else ""
            lines.append(f"[{len(numbers)}] {amount}{item['name']}")
    lines += ["", "Zubereitung:"]
    count = 0
    for step in content.get("steps") or []:
        if "group" in step:
            lines.append(f"{step['group']}:")
        else:
            count += 1
            lines.append(f"Schritt {count}: {step['text']}")
    return "\n".join(lines), numbers, count


async def link_steps(content: dict[str, Any], llm: StructuredLLM) -> list[list[int]]:
    """For each step (headings left out) the positions in `content["ingredients"]` it uses."""
    text, numbers, count = recipe_text(content)
    if not count:
        return []
    if not numbers:
        return [[] for _ in range(count)]
    answer = await llm.structured(
        system=LINKS_PROMPT,
        messages=[{"role": "user", "content": text}],
        output_type=StepLinks,
        max_tokens=2000,
    )
    links: list[set[int]] = [set() for _ in range(count)]
    for link in answer.schritte:
        if 1 <= link.schritt <= count:
            links[link.schritt - 1].update(numbers[n] for n in link.zutaten if n in numbers)
    return [sorted(found) for found in links]


def content_key(content: dict[str, Any]) -> str:
    """Changes when the ingredients or the steps change, not with anything else on the page."""
    relevant = {"ingredients": content.get("ingredients") or [], "steps": [
        {k: v for k, v in step.items() if k != "uses"} for step in content.get("steps") or []
    ]}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class StepLinker:
    """Answers per recipe content: each is asked once, also when two screens ask at the same time."""

    def __init__(self, llm: StructuredLLM, size: int = CACHE_SIZE) -> None:
        self._llm = llm
        self._size = size
        self._done: OrderedDict[str, list[list[int]]] = OrderedDict()
        self._running: dict[str, asyncio.Task[list[list[int]]]] = {}

    async def links(self, content: dict[str, Any]) -> list[list[int]]:
        key = content_key(content)
        if key in self._done:
            self._done.move_to_end(key)
            return self._done[key]
        task = self._running.get(key)
        if task is None:
            task = asyncio.create_task(link_steps(content, self._llm))
            self._running[key] = task
            task.add_done_callback(lambda t, key=key: self._finished(key, t))
        # A screen that closes must not stop the answer the other one is waiting for.
        return await asyncio.shield(task)

    def _finished(self, key: str, task: asyncio.Task[list[list[int]]]) -> None:
        self._running.pop(key, None)
        if task.cancelled() or task.exception() is not None:
            return  # asked again next time
        self._done[key] = task.result()
        while len(self._done) > self._size:
            self._done.popitem(last=False)
