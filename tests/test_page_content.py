"""Turning Notion page content into ingredients, steps and simple blocks for the recipe screen."""

from koch_guru.notion_repo import draft_blocks
from koch_guru.page_content import EmojiFinder, ingredient_line, parse_content
from koch_guru.services.importer import RecipeDraft

EMOJIS = {"Süßkartoffel": "🍠", "Tomate": "🍅", "Mehl 405": "🌾", "Eier": "🥚", "Saure Sahne": "🥛",
          "Kurkuma": "🫙", "Gelbe Linsen": "🫘", "Linsen": "🟤"}


def rich(text, href=None, bold=False):
    part = {"plain_text": text, "annotations": {"bold": bold}}
    if href:
        part["href"] = href
    return part


def block(kind, text="", children=None, **extra):
    data = {"rich_text": [rich(text)] if text else [], **extra}
    item = {"object": "block", "type": kind, kind: data, "has_children": bool(children)}
    if children:
        item["children"] = children
    return item


def image(url, kind="file"):
    return {"type": "image", "image": {"type": kind, kind: {"url": url}, "caption": []}}


def as_read(blocks):
    """Blocks the bot writes, as Notion returns them: plain_text instead of text.content."""
    out = []
    for b in blocks:
        kind = b["type"]
        data = dict(b[kind])
        if "rich_text" in data:
            data["rich_text"] = [
                {"plain_text": t["text"]["content"], "href": (t["text"].get("link") or {}).get("url")}
                for t in data["rich_text"]
            ]
        if kind == "image":
            data = {"type": "file", "file": {"url": "https://files.example/photo.jpg?X-Amz-Signature=1"}}
        out.append({"type": kind, kind: data})
    return out


def test_bot_page_becomes_info_ingredients_steps_and_photo():
    draft = RecipeDraft(
        name="Sweet Potatoes, Tomatoes, Lentils", url="https://example.com/r",
        ingredients=["600 g Süßkartoffeln", "200 g gelbe Linsen", "1 TL Kurkuma", "2 Eier", "Salz"],
        steps=["Süßkartoffeln würfeln.", "Alles 25 Minuten köcheln."],
        total_minutes=45, servings="4 Portionen",
    )
    content = parse_content(as_read(draft_blocks(draft, ["upload-1"])),
                            ingredients=["Süßkartoffel", "Gelbe Linsen", "Kurkuma"], emoji_by_name=EMOJIS)
    assert content["minutes"] == 45
    assert content["servings"] == "4 Portionen"
    assert content["ingredients"] == [
        {"name": "Süßkartoffeln", "amount": "600 g", "emoji": "🍠"},
        {"name": "gelbe Linsen", "amount": "200 g", "emoji": "🫘"},
        {"name": "Kurkuma", "amount": "1 TL", "emoji": "🫙"},
        {"name": "Eier", "amount": "2", "emoji": "🥚"},
        {"name": "Salz", "amount": None, "emoji": None},
    ]
    assert content["steps"] == [{"text": "Süßkartoffeln würfeln."}, {"text": "Alles 25 Minuten köcheln."}]
    assert content["blocks"] == [
        {"type": "heading", "level": 2, "text": [{"text": "Originalfoto"}]},
        {"type": "image", "url": "https://files.example/photo.jpg?X-Amz-Signature=1", "caption": ""},
    ]


def test_page_without_ingredient_list_shows_linked_ingredients():
    blocks = [
        block("paragraph", "Rezept von Oma, mit mehr Knoblauch."),
        {"type": "bookmark", "bookmark": {"url": "https://example.com/video", "caption": []}},
        block("paragraph", ""),
    ]
    content = parse_content(blocks, ingredients=["Tomate", "Nudeln"], emoji_by_name=EMOJIS)
    assert content["ingredients"] == [
        {"name": "Tomate", "amount": None, "emoji": "🍅"},
        {"name": "Nudeln", "amount": None, "emoji": None},
    ]
    assert content["steps"] == []
    assert content["minutes"] is None
    assert content["blocks"] == [
        {"type": "paragraph", "text": [{"text": "Rezept von Oma, mit mehr Knoblauch."}]},
        {"type": "link", "url": "https://example.com/video", "caption": ""},
    ]


def test_headings_in_english_groups_and_nested_items():
    blocks = [
        block("heading_1", "Ingredients"),
        block("heading_3", "Für den Teig"),
        block("bulleted_list_item", "500 g Mehl"),
        block("paragraph", "Für die Soße:"),
        block("bulleted_list_item", "Tomaten", children=[block("bulleted_list_item", "1 Dose Kirschtomaten")]),
        block("heading_2", "Method"),
        block("numbered_list_item", "Teig kneten."),
        block("paragraph", "Soße kochen.\nAbschmecken."),
        block("heading_2", "Notizen"),
        block("to_do", "Mehr Salz", checked=True),
    ]
    content = parse_content(blocks, emoji_by_name=EMOJIS)
    assert content["ingredients"] == [
        {"group": "Für den Teig"},
        {"name": "Mehl", "amount": "500 g", "emoji": "🌾"},
        {"group": "Für die Soße"},
        {"name": "Tomaten", "amount": None, "emoji": "🍅"},
        {"name": "Kirschtomaten", "amount": "1 Dose", "emoji": "🍅"},
    ]
    assert content["steps"] == [{"text": "Teig kneten."}, {"text": "Soße kochen."}, {"text": "Abschmecken."}]
    assert content["blocks"] == [
        {"type": "heading", "level": 2, "text": [{"text": "Notizen"}]},
        {"type": "todo", "text": [{"text": "Mehr Salz"}], "checked": True},
    ]


def test_rich_text_links_and_columns_are_kept():
    blocks = [
        {"type": "column_list", "column_list": {}, "children": [
            {"type": "column", "column": {}, "children": [
                {"type": "paragraph", "paragraph": {"rich_text": [rich("Quelle", "https://x.example", bold=True)]}},
            ]},
            {"type": "column", "column": {}, "children": [image("https://img.example/a.jpg", "external")]},
        ]},
        {"type": "table", "table": {}},
    ]
    assert parse_content(blocks)["blocks"] == [
        {"type": "paragraph", "text": [{"text": "Quelle", "href": "https://x.example", "bold": True}]},
        {"type": "image", "url": "https://img.example/a.jpg", "caption": ""},
    ]


def test_amounts():
    find = EmojiFinder([], {})
    cases = {
        "2 EL Olivenöl": ("2 EL", "Olivenöl"),
        "500g Mehl": ("500g", "Mehl"),
        "1/2 TL Zimt": ("1/2 TL", "Zimt"),
        "3-4 Kartoffeln": ("3-4", "Kartoffeln"),
        "½ Bund Petersilie": ("½ Bund", "Petersilie"),
        "1 Lauchstange": ("1", "Lauchstange"),
        "• 200 ml Sahne": ("200 ml", "Sahne"),
        "Salz und Pfeffer": (None, "Salz und Pfeffer"),
    }
    for line, (amount, name) in cases.items():
        item = ingredient_line(line, find)
        assert (item["amount"], item["name"]) == (amount, name), line


def test_emoji_finder():
    find = EmojiFinder(["Linsen"], EMOJIS)
    assert find("Kirschtomaten") == "🍅"  # end of a compound
    assert find("Tomatenmark") is None  # Tomatenmark is Mark, not a Tomate
    assert find("Grießbrei") is None  # "Ei" only on its own
    assert find("Eier") == "🥚"
    assert find("saure Sahne") == "🥛"
    assert find("gelbe Linsen") == "🟤"  # the recipe's own ingredient comes first


def paragraphs(*lines, kind="paragraph"):
    return [block(kind, line) for line in lines]


def test_page_without_headings_guesses_ingredients_then_steps():
    # As many pages in Philip's Notion: bullets, a group line, then sentences.
    blocks = [
        *paragraphs("450 g Pasta", "4 Handvoll Babyspinat", "1 Knoblauchzehe", kind="bulleted_list_item"),
        *paragraphs(
            "Salt and pepper",
            "For decoration",
            "2 balls of burrata",
            "Blanch the peas for 60 seconds in salted water. Drain and plunge them into ice water.",
            "Keep 1-2 handfuls for decoration.",
        ),
    ]
    content = parse_content(blocks, ingredients=["Pasta"], emoji_by_name={"Pasta": "🍝"})
    assert [i.get("name") or i.get("group") for i in content["ingredients"]] == [
        "Pasta", "Babyspinat", "Knoblauchzehe", "Salt and pepper", "For decoration", "balls of burrata",
    ]
    assert content["ingredients"][0] == {"name": "Pasta", "amount": "450 g", "emoji": "🍝"}
    assert content["steps"] == [
        {"text": "Blanch the peas for 60 seconds in salted water. Drain and plunge them into ice water."},
        {"text": "Keep 1-2 handfuls for decoration."},
    ]
    assert content["blocks"] == []


def test_marker_lines_numbered_steps_and_servings():
    blocks = paragraphs(
        "Serves 2.",
        "For the tofu:",
        "▫️300g firm tofu",
        "▫️1 tbsp cornflour",
        "▫️2 cloves of garlic, minced",
        "Instructions:",
        "1. Tear your block of tofu into nugget sized pieces and bake them for 25 minutes.",
        "2. Serve with rice.",
        "ENJOY!",
    )
    content = parse_content(blocks)
    assert content["servings"] == "2"
    assert content["ingredients"] == [
        {"group": "For the tofu"},
        {"name": "firm tofu", "amount": "300g", "emoji": None},
        {"name": "cornflour", "amount": "1 tbsp", "emoji": None},
        {"name": "garlic, minced", "amount": "2 cloves", "emoji": None},
    ]
    assert content["steps"] == [
        {"text": "Tear your block of tofu into nugget sized pieces and bake them for 25 minutes."},
        {"text": "Serve with rice."},
        {"text": "ENJOY!"},
    ]


def test_notes_pages_are_not_mistaken_for_recipes():
    toggles_first = [
        block("toggle", "Original try", children=[block("paragraph", "no baking powder")]),
        *paragraphs("Learnings"),
        *paragraphs("not too sweet", "not too fudgy", "Bake @ 180", kind="bulleted_list_item"),
    ]
    content = parse_content(toggles_first, ingredients=["Zitrone"])
    assert content["ingredients"] == [{"name": "Zitrone", "amount": None, "emoji": None}]
    assert content["steps"] == []
    assert len(content["blocks"]) == 5

    few_short_lines = paragraphs("Apfelessig mit 5% Säure", "Banh-mi is a fresh pickle!", "My fruit jam i can preserve")
    content = parse_content(few_short_lines)
    assert content["ingredients"] == [] and content["steps"] == []
    assert len(content["blocks"]) == 3
