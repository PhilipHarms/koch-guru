from telegram import Update
from telegram.ext import ContextTypes
from gpt.gpt_client import ask_gpt
from notion.recipe_utils import get_random_recipes

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.strip().lower()

    if "notion" in user_message or "aus datenbank" in user_message:
        await update.message.reply_text("Hole zufällige Rezepte aus der Notion-Datenbank… 🗂️")

        recipes = get_random_recipes()
        if not recipes:
            await update.message.reply_text("Leider keine Rezepte gefunden.")
            return

        message = "Hier sind ein paar Rezeptideen aus deiner Sammlung:\n\n"
        for i, r in enumerate(recipes, start=1):
            line = f"{i}. {r['name']}"
            if r["link"]:
                line += f" → [Link]({r['link']})"
            message += line + "\n"
        
        await update.message.reply_text(message, parse_mode="Markdown")

    elif "neu" in user_message or "nicht in Notion" in user_message:
        await update.message.reply_text("Einen Moment, ich suche passende Rezeptideen für dich… 🍳")
        gpt_response = ask_gpt(user_message)
        await update.message.reply_text(gpt_response)

    else:
        from notion.recipe_utils import get_all_recipes_with_tags
        from gpt.gpt_client import suggest_tagged_recipes_from_list

        await update.message.reply_text("Ich schau mal, was ich dir aus deiner Sammlung vorschlagen kann... 🧠🍲")
        recipes = get_all_recipes_with_tags()
        gpt_response = suggest_tagged_recipes_from_list(user_message, recipes)
        await update.message.reply_text(gpt_response, parse_mode="Markdown")