from notion.notion_client import notion
from config import NOTION_DATABASE_ID
import random

def get_random_recipes(limit=4):
    # Alle Rezepte holen
    response = notion.databases.query(database_id=NOTION_DATABASE_ID)
    recipes = response.get("results", [])

    # Rezepte extrahieren: Name + ggf. Link oder Tags
    simplified = []
    for recipe in recipes:
        props = recipe["properties"]
        name = props["Recipe"]["title"][0]["text"]["content"] if props["Recipe"]["title"] else "Unbenannt"
        link = props["Link"]["url"] if "Link" in props and props["Link"]["url"] else None
        simplified.append({"name": name, "link": link, "id": recipe["id"]})

    # Zufällig auswählen
    return random.sample(simplified, min(limit, len(simplified)))

def get_all_recipes_with_ingredients():
    response = notion.databases.query(database_id=NOTION_DATABASE_ID)
    recipes = response.get("results", [])

    structured = []
    for recipe in recipes:
        props = recipe["properties"]

        name = props["Recipe"]["title"][0]["text"]["content"] if props["Recipe"]["title"] else "Unbenannt"
        link = props["Link"]["url"] if "Link" in props and props["Link"]["url"] else None

        # Zutaten: Multi-Select oder Rich Text unterstützen
        if "Zutaten" in props:
            if props["Zutaten"]["type"] == "multi_select":
                zutaten = [tag["name"] for tag in props["Zutaten"]["multi_select"]]
            elif props["Zutaten"]["type"] == "rich_text":
                zutaten = [props["Zutaten"]["rich_text"][0]["plain_text"]] if props["Zutaten"]["rich_text"] else []
            else:
                zutaten = []
        else:
            zutaten = []

        structured.append({
            "name": name,
            "link": link,
            "zutaten": zutaten
        })

    return structured

def get_all_recipes_with_tags():
    response = notion.databases.query(database_id=NOTION_DATABASE_ID)
    recipes = response.get("results", [])

    structured = []
    for recipe in recipes:
        props = recipe["properties"]

        name = props["Recipe"]["title"][0]["text"]["content"] if props["Recipe"]["title"] else "Unbenannt"
        link = props["Link"]["url"] if "Link" in props and props["Link"]["url"] else None

        # Tags: Multi-select
        if "Tags" in props and props["Tags"]["type"] == "multi_select":
            tags = [tag["name"] for tag in props["Tags"]["multi_select"]]
        else:
            tags = []

        # Zutaten (optional)
        if "Zutaten" in props:
            if props["Zutaten"]["type"] == "multi_select":
                zutaten = [z["name"] for z in props["Zutaten"]["multi_select"]]
            elif props["Zutaten"]["type"] == "rich_text":
                zutaten = [props["Zutaten"]["rich_text"][0]["plain_text"]] if props["Zutaten"]["rich_text"] else []
            else:
                zutaten = []
        else:
            zutaten = []

        structured.append({
            "name": name,
            "link": link,
            "tags": tags,
            "zutaten": zutaten
        })

    return structured