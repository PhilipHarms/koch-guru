"""Rezept generieren: read a recipe from a link or photos, write it in German, match ingredients."""

import json

import httpx
import pytest

from koch_guru.services.generate import PreparedIngredient, PreparedRecipe, generate, prepare
from koch_guru.services.importer import ExtractedRecipe, RecipeDraft, RecipeImportError

KNOWN = ["Sojasauce", "Zwiebel", "Eier", "Salz", "Mehl 405"]


def prepared(*items, steps=("Tofu backen.",), portionen="2 Portionen"):
    return PreparedRecipe(
        zutaten=[PreparedIngredient(zeile=z, zutat=n, emoji=e, immer_da=s, gruppe=bool(rest and rest[0]))
                 for z, n, e, s, *rest in items],
        schritte=list(steps),
        portionen=portionen,
    )


class FakeLLM:
    def __init__(self, result, extracted=None):
        self.result, self.extracted = result, extracted
        self.calls = []

    async def structured(self, *, system, messages, output_type):
        self.calls.append(output_type)
        if output_type is PreparedRecipe:
            return self.result
        if output_type is ExtractedRecipe:
            return self.extracted
        raise AssertionError(output_type)


async def test_prepare_matches_ingredients_and_preselects():
    llm = FakeLLM(prepared(
        ("2 EL dunkle Sojasauce", "Sojasauce", "🥢", False),
        ("1 große Zwiebel", "Zwiebel", "🧅", False),
        ("2 Eier", "Ei", "🥚", False),
        ("200 g Pak Choi", "Pak Choi", "🥬", False),
        ("1 Prise Salz", "Salz", "🧂", True),
        ("500 g Mehl", "Weizenmehl", "🌾", False),
    ))
    draft = RecipeDraft(name="Tofu", url="https://example.com/tofu", ingredients=["x"], total_minutes=30)
    result = (await prepare(draft, llm, KNOWN, linked=["Zwiebel"])).as_json()
    rows = [(i["zutat"], i["status"], i["include"], i["amount"], i["name"]) for i in result["ingredients"]]
    assert rows == [
        ("Sojasauce", "existing", True, "2 EL", "dunkle Sojasauce"),
        ("Zwiebel", "linked", True, "1", "große Zwiebel"),
        ("Eier", "existing", True, "2", "Eier"),
        ("Pak Choi", "new", True, "200 g", "Pak Choi"),
        ("Salz", "existing", False, "1 Prise", "Salz"),
        ("Mehl 405", "existing", True, "500 g", "Mehl"),  # Weizenmehl is a Mehl
    ]
    assert result["servings"] == "2 Portionen" and result["minutes"] == 30
    assert result["steps"] == ["Tofu backen."]
    assert result["source"] == "https://example.com/tofu"


async def test_prepare_keeps_group_headings_unlinked():
    """Jamie Oliver lists "Pineapple salsa" and "Guacamole" between the ingredients."""
    llm = FakeLLM(prepared(
        ("4 große Weizentortillas", "Tortillas", "🫓", False),
        ("Für die Ananas-Salsa", "", "", False, True),
        ("½ TL schwarze Senfsaat", "Senfsaat", "🌱", False),
        ("Guacamole:", "", "", False, True),
    ))
    draft = RecipeDraft(name="Quesadillas", url="https://example.com/q", ingredients=["x"])
    result = (await prepare(draft, llm, KNOWN, linked=[])).as_json()
    rows = [(i["line"], i["status"], i["include"], i["name"]) for i in result["ingredients"]]
    assert rows == [
        ("4 große Weizentortillas", "new", True, "große Weizentortillas"),
        ("Für die Ananas-Salsa:", "group", False, "Für die Ananas-Salsa"),
        ("½ TL schwarze Senfsaat", "new", True, "schwarze Senfsaat"),
        ("Guacamole:", "group", False, "Guacamole"),
    ]


JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@type": "Recipe", "name": "Sticky Tofu", "recipeIngredient": ["300g firm tofu", "2 tbsp soy sauce"],
 "recipeInstructions": ["Bake the tofu.", "Add the sauce."], "recipeYield": "2",
 "image": "https://example.com/tofu.jpg"}
</script></head><body></body></html>"""


def http_with(routes):
    def handler(request):
        status, body, ctype = routes.get(str(request.url), (404, b"", "text/html"))
        return httpx.Response(status, content=body if isinstance(body, bytes) else body.encode(),
                              headers={"content-type": ctype})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_generate_from_link_with_jsonld_needs_one_model_call():
    http = http_with({"https://example.com/tofu": (200, JSONLD_PAGE, "text/html")})
    llm = FakeLLM(prepared(("300 g fester Tofu", "Tofu", "🧈", False), ("2 EL Sojasauce", "Sojasauce", "🥢", False),
                           steps=("Tofu backen.", "Soße dazugeben.")))
    result = await generate(link="https://example.com/tofu", notes="", photo_urls=[], http=http, llm=llm,
                            known=KNOWN, linked=[])
    assert llm.calls == [PreparedRecipe]
    assert result.image == "https://example.com/tofu.jpg"
    assert [i.line for i in result.ingredients] == ["300 g fester Tofu", "2 EL Sojasauce"]
    assert result.steps == ["Tofu backen.", "Soße dazugeben."]


NOTES = "Teig: 500 g Mehl, 1 Päckchen Hefe und 300 ml Wasser verkneten, eine Stunde gehen lassen. Dann backen."


def extracted(name="Fladenbrot", zutaten=("500 g Mehl",)):
    return ExtractedRecipe(ist_rezept=True, name=name, zutaten=list(zutaten), schritte=["Backen."],
                           portionen="", minuten=0, tags=[], emoji="🍞")


async def test_generate_from_photos_on_the_page():
    http = http_with({"https://files.example/a.jpg": (200, b"jpeg", "image/jpeg"),
                      "https://files.example/b.txt": (200, b"text", "text/plain")})
    llm = FakeLLM(prepared(("200 g Mehl", "Mehl", "🌾", False)), extracted=extracted())
    result = await generate(link=None, notes="", photo_urls=["https://files.example/a.jpg", "https://files.example/b.txt"],
                            http=http, llm=llm, known=KNOWN, linked=[])
    assert llm.calls == [ExtractedRecipe, PreparedRecipe]
    assert result.source == "Notizen" and result.url is None
    assert result.ingredients[0].existing == "Mehl 405"


async def test_link_without_recipe_falls_back_to_the_notes():
    short = http_with({"https://instagram.example/p/1": (200, "<html><body>Login</body></html>", "text/html")})
    llm = FakeLLM(prepared(("500 g Mehl", "Mehl", "🌾", False)), extracted=extracted())
    result = await generate(link="https://instagram.example/p/1", notes=NOTES, photo_urls=[], http=short, llm=llm,
                            known=KNOWN, linked=[])
    assert llm.calls == [ExtractedRecipe, PreparedRecipe]
    assert result.source == "Notizen"


async def test_generate_without_source_or_readable_page():
    llm = FakeLLM(prepared())
    with pytest.raises(RecipeImportError, match="weder einen Link"):
        await generate(link=None, notes="kurz", photo_urls=[], http=http_with({}), llm=llm, known=[], linked=[])
    short = http_with({"https://instagram.example/p/1": (200, "<html><body>Login</body></html>", "text/html")})
    with pytest.raises(RecipeImportError, match="kaum Text"):
        await generate(link="https://instagram.example/p/1", notes="", photo_urls=[], http=short, llm=llm,
                       known=[], linked=[])
    no_recipe = FakeLLM(prepared(), extracted=ExtractedRecipe(ist_rezept=False, name="", zutaten=[], schritte=[],
                                                              portionen="", minuten=0, tags=[], emoji=""))
    with pytest.raises(RecipeImportError, match="kein Rezept"):
        await generate(link=None, notes=NOTES, photo_urls=[], http=http_with({}), llm=no_recipe, known=[], linked=[])
