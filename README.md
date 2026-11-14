# 🧠 KochGuru

KochGuru ist ein privater Telegram-Bot, der Rezepte aus einer Notion-Rezeptdatenbank vorschlägt. Die Auswahl trifft Claude (über OpenRouter), aber ausschließlich aus den Rezepten in Notion.

## Was der Bot kann

- Freitext verstehen: „was Schnelles, vegetarisch“, „wir haben noch Brokkoli und Feta“, „Ideen für die Woche“
- Bis zu vier passende Rezepte mit Link und kurzer Begründung vorschlagen, oder ehrlich sagen, dass nichts passt
- Rückfragen verstehen („lieber ohne Fleisch“, „noch was anderes“); der Verlauf gilt pro Chat und wird nach zwei Stunden Pause oder mit `/neu` vergessen
- Wochenliste: 📅 unter einem Vorschlag setzt die Checkbox „This Week?“ in Notion, ✅ nimmt sie wieder raus
- `/woche`: Wochenliste anzeigen, `/woche_leeren`: alle Häkchen entfernen
- Rezepte per Link anlegen: Link schicken, Vorschau prüfen, „Speichern“ legt die Seite in Notion an (Name, Link, passende Tags aus den bestehenden, Titelbild, Zutaten und Zubereitung im Seiteninhalt). Ist der Link schon in der Sammlung, sagt der Bot das. Seiten, die ihren Inhalt erst per JavaScript laden (Instagram, TikTok), kann er nicht lesen.
- `/zufall`: vier zufällige Rezepte
- `/aktualisieren`: Rezepte sofort neu aus Notion laden (sonst alle 5 Minuten automatisch)

Geplant: Zutaten-Verknüpfung beim Import, „Zuletzt gekocht“ und Zubereitungszeit (erst testweise für einzelne Rezepte), Rezepte per Foto anlegen.

## Aufbau

```
main.py                     Einstiegspunkt (Railway startet `python main.py`)
koch_guru/
  config.py                 Umgebungsvariablen lesen und prüfen
  models.py                 Recipe-Datenklasse
  notion_repo.py            Notion-Zugriff: Datenquelle, Property-Mapping, Pagination, Cache
  llm.py                    OpenRouter-Client mit Structured Output
  services/recommend.py     Prompt, Auswahl und Validierung der Empfehlungen
  services/conversation.py  Kurzzeit-Gesprächsverlauf pro Chat (im Speicher)
  services/importer.py      Rezept aus einer URL lesen (schema.org/JSON-LD, sonst Seitentext an das Modell)
  services/drafts.py        Import-Entwürfe bis „Speichern“ oder „Verwerfen“ (im Speicher)
  bot/app.py                Telegram-Anwendung, Zugriffsschutz, Fehlerbehandlung
  bot/handlers.py           Befehle und Nachrichten
  bot/render.py             Telegram-HTML mit Escaping
tests/                      Tests ohne Netzwerkzugriff
```

Grundprinzip: Claude liefert nur Nummern aus der Rezeptliste plus Begründung. Der Code prüft die Nummern gegen Notion und baut die Nachricht selbst. Dadurch kann der Bot keine Rezepte erfinden, und die Formatierung bricht nicht.

## Umgebungsvariablen

| Variable | Pflicht | Beschreibung |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | ja | Bot-Token von BotFather |
| `NOTION_TOKEN` | ja | Token der Notion-Integration mit Zugriff auf die Rezeptdatenbank |
| `NOTION_DATABASE_ID` | ja | ID (oder URL) der Rezeptdatenbank |
| `OPENROUTER_API_KEY` | ja | API-Key von OpenRouter |
| `ALLOWED_USER_IDS` | empfohlen | Komma-getrennte Telegram-User-IDs, die den Bot nutzen dürfen. Leer: Der Bot antwortet allen nur mit ihrer eigenen ID. |
| `OPENROUTER_MODEL` | nein | Modell-Slug bei OpenRouter, Standard `anthropic/claude-sonnet-5.5` |
| `RECIPE_CACHE_SECONDS` | nein | Standard 300 |
| `NOTION_PROP_LINK`, `NOTION_PROP_TAGS`, `NOTION_PROP_ORIGIN`, `NOTION_PROP_INGREDIENTS`, `NOTION_PROP_THIS_WEEK` | nein | Property-Namen, Standard `Link`, `Tags`, `Origin`, `Ingredients`, `This Week?` |

Die Titel-Property wird automatisch erkannt. Fehlt die Link-Property unter dem erwarteten Namen, nimmt der Bot die erste URL-Property. Beim Start steht im Log, welche Properties verwendet werden.

## Notion-Integration

- **Zutaten:** `Ingredients` ist eine Verknüpfung zu einer eigenen Zutaten-Datenbank. Damit der Bot die Zutatennamen lesen kann, muss auch diese Datenbank mit der Integration verbunden sein (Datenbank öffnen › ••• › Connections). Ohne Zugriff lädt der Bot die Rezepte ohne Zutaten und schreibt einen Hinweis ins Log.
- **Wochenliste:** Zum Setzen der Checkbox braucht die Integration die Berechtigung „Update content“.
- **Link-Import:** Zum Anlegen neuer Rezepte braucht sie „Insert content“.

Die eigene Telegram-ID findest du, indem du dem Bot schreibst, solange `ALLOWED_USER_IDS` leer ist.

## Lokal starten

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # Werte eintragen
python main.py
pytest
```

Wichtig: Läuft der Bot gleichzeitig auf Railway, verteilt Telegram die Nachrichten zufällig auf beide Instanzen (Fehler „terminated by other getUpdates request“). Lokal daher am besten mit einem zweiten Test-Bot-Token arbeiten.

## Deployment auf Railway

Railway baut aus `requirements.txt` und startet `python main.py`. Die Python-Version steht in `.python-version`. Benötigte Variablen: `TELEGRAM_TOKEN`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `OPENROUTER_API_KEY` und `ALLOWED_USER_IDS`.

Im OpenRouter-Dashboard erscheinen die Anfragen unter dem App-Namen „KochGuru“.
