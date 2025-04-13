from openai import OpenAI
from config import OPENAI_API_KEY
from datetime import datetime

client = OpenAI(api_key=OPENAI_API_KEY)

def ask_gpt(prompt: str, temperature: float = 0.7) -> str:
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": (
                "Du bist ein smarter Küchenassistent. "
                "Schlage kreative, leckere und alltagstaugliche Rezepte vor. "
                "Berücksichtige Präferenzen wie vegetarisch, schnell, oder saisonal. "
                "Antworten bitte freundlich und nicht zu lang."
            )},
            {"role": "user", "content": prompt}
        ],
        temperature=temperature
    )
    return response.choices[0].message.content.strip()

def suggest_recipes_from_list(user_message: str, recipes: list, limit: int = 4) -> str:
    """
    Nutzt GPT, um aus einer bestehenden Rezeptliste passende Vorschläge basierend auf dem User-Input zu wählen.
    """
    recipe_list_str = "\n".join(
        [f"- {r['name']}: {', '.join(r['zutaten'])}" for r in recipes]
    )

    system_prompt = (
        "Du bist ein kreativer Küchenassistent. "
        "Du bekommst eine Liste von Rezepten mit Zutaten und einen Wunsch oder Kommentar von einem Nutzer. "
        "Wähle basierend auf dem Wunsch 3–4 passende Rezepte aus der Liste. "
        "Gib die Auswahl in schöner, lesbarer Liste zurück. "
        "Wähle nur Rezepte aus der Liste, keine neuen erfinden."
    )

    full_prompt = (
        f"Rezeptliste:\n{recipe_list_str}\n\n"
        f"Nachricht vom Nutzer:\n\"{user_message}\"\n\n"
        f"Wähle {limit} passende Rezepte aus."
    )

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()

def format_recipe_entry(r):
    entry = f"- {r['name']} | Tags: {', '.join(r['tags'])}"
    if r["zutaten"]:
        entry += f" | Zutaten: {', '.join(r['zutaten'])}"
    return entry

def suggest_tagged_recipes_from_list(user_message: str, recipes: list, limit: int = 4) -> str:
    """
    GPT wählt passende Rezepte aus einer Liste mit Namen, Tags und Zutaten, basierend auf Nutzer-Feedback.
    """
    recipe_list_str = "\n".join([format_recipe_entry(r) for r in recipes])

    monat = datetime.now().strftime("%B")

    system_prompt = (
        "Du bist ein smarter Küchenassistent. "
        "Dir liegt eine Liste an Rezepten vor, jeweils mit Namen, Tags (z. B. 'Fleisch', 'Veggie', 'Asiatisch') und Zutaten. "
        "Der Nutzer hat dir Wünsche oder Einschränkungen genannt. "
        "Wähle daraus 3–4 passende Rezepte. "
        "Beziehe dich NUR auf die vorliegenden Rezepte, erfinde keine neuen. "
        "Formatiere sie als freundliche Liste. Gib keine Rohdaten oder JSON zurück."
    )

    full_prompt = (
        f"Rezeptliste:\n{recipe_list_str}\n\n"
        f"Aktuell ist der Monat {monat}. Berücksichtige das bei saisonalen Wünschen.\n\n"
        f"Nachricht vom Nutzer:\n\"{user_message}\"\n\n"
        f"Wähle {limit} passende Rezepte aus der Liste und gib sie schön formatiert zurück."
    )

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_prompt}
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()