import xml.etree.ElementTree as ET

from koch_guru.bot.render import render_recipe_list, render_recommendation
from koch_guru.models import Recipe
from koch_guru.services.recommend import Recommendation, Suggestion

TELEGRAM_TAGS = {"b", "i", "a"}

TRICKY = Recipe(
    id="p1",
    name='Spaghetti_Carbonara <"Original"> & *mehr*',
    notion_url="https://www.notion.so/p1",
    url="https://example.com/rezept_carbonara?a=1&b=2",
)


def assert_valid_telegram_html(html: str):
    root = ET.fromstring(f"<root>{html}</root>")  # raises on unbalanced tags / bad entities
    assert {el.tag for el in root.iter()} - {"root"} <= TELEGRAM_TAGS


def test_recommendation_is_escaped_and_well_formed():
    rec = Recommendation(
        message="Hier <3 & mehr: *fett*?",
        suggestions=[Suggestion(TRICKY, reason="weil _lecker_ & schnell")],
    )
    html = render_recommendation(rec)
    assert_valid_telegram_html(html)
    assert "Hier &lt;3 &amp; mehr: *fett*?" in html
    assert 'href="https://example.com/rezept_carbonara?a=1&amp;b=2"' in html
    assert "&lt;&quot;Original&quot;&gt;" in html


def test_empty_recommendation_has_fallback_text():
    assert render_recommendation(Recommendation(message="", suggestions=[]))


def test_recipe_list():
    html = render_recipe_list("Zufall:", [TRICKY])
    assert_valid_telegram_html(html)
    assert html.startswith("Zufall:\n\n1. <a href=")
