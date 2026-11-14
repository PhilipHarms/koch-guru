import json

import httpx
import pytest

from koch_guru.services.importer import (
    ExtractedRecipe,
    RecipeImportError,
    Classification,
    draft_from_jsonld,
    clean_emoji,
    filter_tags,
    find_jsonld_recipe,
    find_url,
    import_from_url,
    normalize_url,
    page_text,
    parse_duration,
)

TAGS = ["Veggie", "Winter", "New", "Pasta"]


def jsonld_page(data, extra=""):
    return (
        "<html><head><title>x</title>"
        f'<script type="application/ld+json">{json.dumps(data)}</script>{extra}'
        "</head><body><p>Text</p></body></html>"
    )


RECIPE = {
    "@context": "https://schema.org",
    "@type": "Recipe",
    "name": "Ofen-Süßkartoffeln mit Feta &amp; Linsen",
    "recipeIngredient": ["500 g Süßkartoffeln", "200 g Feta", "Cr&egrave;me fra&icirc;che", ""],
    "recipeInstructions": [
        {"@type": "HowToSection", "name": "Vorbereiten", "itemListElement": [
            {"@type": "HowToStep", "text": "Ofen auf 200 °C vorheizen."},
            {"@type": "HowToStep", "text": "Kartoffeln <b>würfeln</b>."},
        ]},
        {"@type": "HowToStep", "text": "30 Minuten backen."},
    ],
    "prepTime": "PT15M",
    "cookTime": "PT30M",
    "recipeYield": ["4", "4 Portionen"],
    "image": [{"@type": "ImageObject", "url": "https://img.example/a.jpg"}],
}


def test_find_url_strips_trailing_punctuation():
    assert find_url("Schau mal: https://www.chefkoch.de/rezepte/123/abc.html!") == (
        "https://www.chefkoch.de/rezepte/123/abc.html"
    )
    assert find_url("ohne Link") is None


def test_normalize_url_ignores_scheme_www_slash_and_fragment():
    assert normalize_url("https://www.Chefkoch.de/rezepte/1/") == normalize_url("http://chefkoch.de/rezepte/1#x")
    assert normalize_url("https://a.de/r?id=1") != normalize_url("https://a.de/r?id=2")


@pytest.mark.parametrize("value, minutes", [
    ("PT1H30M", 90), ("PT45M", 45), ("P0DT1H0M", 60), ("pt20m", 20), ("PT0S", None), ("abc", None), (None, None),
])
def test_parse_duration(value, minutes):
    assert parse_duration(value) == minutes


def test_jsonld_recipe_from_graph_and_type_list():
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "WebPage", "name": "Seite"},
        {**RECIPE, "@type": ["Recipe", "NewsArticle"]},
    ]}
    assert find_jsonld_recipe(jsonld_page(graph))["name"].startswith("Ofen")
    assert find_jsonld_recipe(jsonld_page([{"@type": "Organization"}, RECIPE]))["name"].startswith("Ofen")
    assert find_jsonld_recipe(jsonld_page({"@type": "Article", "name": "kein Rezept"})) is None


def test_jsonld_with_trailing_commas_is_still_read():
    broken = '{"@type": "Recipe", "name": "Suppe", "recipeIngredient": ["Wasser",],}'
    page = f'<script type="application/ld+json">{broken}</script>'
    assert find_jsonld_recipe(page)["name"] == "Suppe"


def test_draft_from_jsonld_cleans_and_flattens():
    draft = draft_from_jsonld(RECIPE, "https://example.com/r")
    assert draft.name == "Ofen-Süßkartoffeln mit Feta & Linsen"
    assert draft.ingredients == ["500 g Süßkartoffeln", "200 g Feta", "Crème fraîche"]
    assert draft.steps == ["Ofen auf 200 °C vorheizen.", "Kartoffeln würfeln.", "30 Minuten backen."]
    assert draft.total_minutes == 45
    assert draft.servings == "4"
    assert draft.image == "https://img.example/a.jpg"
    assert draft.site == "example.com"


def test_instructions_as_html_string():
    data = {**RECIPE, "recipeInstructions": "<p>Erst das.</p><p>Dann das.<br>Fertig.</p>", "totalTime": "PT1H"}
    draft = draft_from_jsonld(data, "https://x.de")
    assert draft.steps == ["Erst das.", "Dann das.", "Fertig."]
    assert draft.total_minutes == 60


def test_jsonld_without_ingredients_is_not_enough():
    assert draft_from_jsonld({"@type": "Recipe", "name": "Leer"}, "https://x.de") is None


def test_page_text_skips_scripts_and_reads_meta():
    text, meta = page_text(
        '<html><head><meta property="og:image" content="https://img/x.jpg"><script>var a=1;</script></head>'
        "<body><nav>Menü</nav><h1>Linsensuppe</h1><p>Zutaten: Linsen</p></body></html>"
    )
    assert text == "Linsensuppe\nZutaten: Linsen"
    assert meta["og:image"] == "https://img/x.jpg"


def test_filter_tags_keeps_only_existing_options_in_their_spelling():
    assert filter_tags(["veggie", "Erfunden", "WINTER", "Veggie"], TAGS) == ["Veggie", "Winter"]


class FakeLLM:
    def __init__(self, tags=None, extracted=None, emoji="🍠"):
        self.tags = tags or []
        self.emoji = emoji
        self.extracted = extracted
        self.calls = []

    async def structured(self, *, system, messages, output_type):
        self.calls.append((output_type, system, messages))
        if output_type is Classification:
            return Classification(tags=self.tags, emoji=self.emoji)
        if output_type is ExtractedRecipe:
            return self.extracted
        raise AssertionError(output_type)


def http_client(pages):
    """pages: path -> (status, html, content_type). /redirect redirects to /recipe."""
    def handler(request):
        if request.url.path == "/redirect":
            return httpx.Response(301, headers={"location": "https://example.com/recipe"})
        status, body, ctype = pages.get(request.url.path, (404, "", "text/html"))
        return httpx.Response(status, text=body, headers={"content-type": ctype})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


async def test_import_with_jsonld_uses_model_only_for_tags():
    llm = FakeLLM(tags=["veggie", "Fleisch"])
    http = http_client({"/recipe": (200, jsonld_page(RECIPE), "text/html; charset=utf-8")})
    draft = await import_from_url("https://example.com/redirect", http, llm, TAGS)
    assert draft.url == "https://example.com/recipe"
    assert draft.tags == ["Veggie"]
    assert draft.source == "json-ld"
    assert draft.icon == "🍠"
    assert [c[0] for c in llm.calls] == [Classification]
    assert "Veggie, Winter, New, Pasta" in llm.calls[0][1]


async def test_import_without_jsonld_reads_page_text_with_model():
    body = ('<html><head><meta property="og:image" content="https://img/og.jpg"></head><body>'
            + "<p>Omas Linsensuppe mit Würstchen und viel Liebe gekocht.</p>" * 10 + "</body></html>")
    extracted = ExtractedRecipe(ist_rezept=True, name="Omas Linsensuppe", zutaten=["250 g Linsen", " "],
                                schritte=["Kochen."], portionen="", minuten=0, tags=["Winter", "Quatsch"],
                                emoji="Suppe")
    llm = FakeLLM(extracted=extracted)
    draft = await import_from_url("https://example.com/recipe", http_client({"/recipe": (200, body, "text/html")}),
                                  llm, TAGS)
    assert (draft.name, draft.ingredients, draft.tags) == ("Omas Linsensuppe", ["250 g Linsen"], ["Winter"])
    assert (draft.servings, draft.total_minutes, draft.image, draft.source) == (None, None, "https://img/og.jpg", "text")
    assert draft.icon == "🍽️"  # "Suppe" is text, not an emoji
    assert "<seite>" in llm.calls[0][2][0]["content"]


async def test_import_rejects_pages_without_recipe():
    body = "<html><body>" + "<p>Nur ein Blogartikel über das Wetter.</p>" * 10 + "</body></html>"
    extracted = ExtractedRecipe(ist_rezept=False, name="", zutaten=[], schritte=[], portionen="", minuten=0, tags=[],
                                emoji="")
    with pytest.raises(RecipeImportError, match="kein Rezept"):
        await import_from_url("https://example.com/recipe", http_client({"/recipe": (200, body, "text/html")}),
                              FakeLLM(extracted=extracted), TAGS)


@pytest.mark.parametrize("pages, message", [
    ({}, "Fehler 404"),
    ({"/recipe": (200, "%PDF", "application/pdf")}, "keine Webseite"),
    ({"/recipe": (200, "<html><body><div id=app></div></body></html>", "text/html")}, "JavaScript"),
])
async def test_import_errors_have_readable_messages(pages, message):
    with pytest.raises(RecipeImportError, match=message):
        await import_from_url("https://example.com/recipe", http_client(pages), FakeLLM(), TAGS)


@pytest.mark.parametrize("value, expected", [
    ("🍝", "🍝"), (" 🍲 ", "🍲"), ("🍽️", "🍽️"), ("👩‍🍳", "👩‍🍳"),
    ("Pasta", None), ("🍝 Pasta", None), ("🍝🍛", "🍝🍛"), ("", None), (None, None), ("1️⃣", None),
])
def test_clean_emoji(value, expected):
    assert clean_emoji(value) == expected


# --- Photos ----------------------------------------------------------------------------

from koch_guru.services.importer import PhotoRecipe, import_from_photos  # noqa: E402

ORIGINS = ["Green Feast (Autumn Winter)", "Ottolenghi Simple"]


def photo_result(**overrides):
    values = dict(ist_rezept=True, name="Kürbis-Dal", zutaten=["1 Kürbis", "200 g rote Linsen"],
                  schritte=["Kochen."], portionen="4", minuten=40, tags=["veggie", "Erfunden"], emoji="🍛",
                  quelle="green feast (autumn winter)")
    values.update(overrides)
    return PhotoRecipe(**values)


class PhotoLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def structured(self, *, system, messages, output_type):
        self.calls.append((system, messages, output_type))
        return self.result


async def test_photos_are_sent_as_images_with_caption():
    llm = PhotoLLM(photo_result())
    photos = [(b"\xff\xd8jpeg-1", "image/jpeg"), (b"png-2", "image/png"), (b"heic", "image/heic")]
    draft = await import_from_photos(photos, "aus Green Feast, S. 112", llm, TAGS, ORIGINS)

    system, messages, output_type = llm.calls[0]
    assert output_type is PhotoRecipe
    assert "Green Feast (Autumn Winter), Ottolenghi Simple" in system
    content = messages[0]["content"]
    assert content[0] == {"type": "text", "text": "Lies das Rezept von diesen Fotos ab.\nBildunterschrift: aus Green Feast, S. 112"}
    assert [c["image_url"]["url"][:22] for c in content[1:]] == ["data:image/jpeg;base64", "data:image/png;base64,"]

    assert (draft.name, draft.url, draft.site, draft.source) == ("Kürbis-Dal", "", "", "photo")
    assert draft.tags == ["Veggie"] and draft.icon == "🍛"
    assert draft.origin == ["Green Feast (Autumn Winter)"]
    assert (draft.servings, draft.total_minutes) == ("4", 40)
    assert len(draft.photos) == 2  # the HEIC file is skipped


async def test_unknown_cookbook_is_not_set():
    draft = await import_from_photos([(b"x", "image/jpeg")], "", PhotoLLM(photo_result(quelle="Mein Notizbuch")),
                                     TAGS, ORIGINS)
    assert draft.origin == []


async def test_photo_without_recipe_or_supported_format():
    with pytest.raises(RecipeImportError, match="kein Rezept"):
        await import_from_photos([(b"x", "image/jpeg")], "", PhotoLLM(photo_result(ist_rezept=False)), TAGS, ORIGINS)
    with pytest.raises(RecipeImportError, match="Bildformat"):
        await import_from_photos([(b"x", "image/heic")], "", PhotoLLM(photo_result()), TAGS, ORIGINS)
