# 🧠 KochGuru

KochGuru ist ein privater Telegram-Bot, der Rezepte aus einer Notion-Rezeptdatenbank vorschlägt. Die Auswahl trifft Claude, aber ausschließlich aus den Rezepten in Notion.

## Was der Bot kann

- Freitext verstehen: „was Schnelles, vegetarisch“, „wir haben noch Brokkoli und Feta“, „Ideen für die Woche“
- Bis zu vier passende Rezepte mit Link und kurzer Begründung vorschlagen, oder ehrlich sagen, dass nichts passt
- `/zufall`: vier zufällige Rezepte
- `/aktualisieren`: Rezepte sofort neu aus Notion laden (sonst alle 5 Minuten automatisch)

Geplant: Gesprächsverlauf und „Cook this Week“, danach neue Rezepte per Link oder Foto anlegen.

## Aufbau

```
main.py                     Einstiegspunkt (Railway startet `python main.py`)
koch_guru/
  config.py                 Umgebungsvariablen lesen und prüfen
  models.py                 Recipe-Datenklasse
  notion_repo.py            Notion-Zugriff: Datenquelle, Property-Mapping, Pagination, Cache
  llm.py                    Claude-Client mit Structured Output
  services/recommend.py     Prompt, Auswahl und Validierung der Empfehlungen
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
| `ANTHROPIC_API_KEY` | ja | API-Key für Claude |
| `ALLOWED_USER_IDS` | empfohlen | Komma-getrennte Telegram-User-IDs, die den Bot nutzen dürfen. Leer: Der Bot antwortet allen nur mit ihrer eigenen ID. |
| `ANTHROPIC_MODEL` | nein | Standard `claude-sonnet-5-5` |
| `ANTHROPIC_EFFORT` | nein | `low`, `medium` (Standard), `high`, `xhigh`, `max` |
| `RECIPE_CACHE_SECONDS` | nein | Standard 300 |
| `NOTION_PROP_LINK`, `NOTION_PROP_TAGS`, `NOTION_PROP_INGREDIENTS` | nein | Property-Namen, Standard `Link`, `Tags`, `Zutaten` |

Die Titel-Property wird automatisch erkannt. Fehlt die Link-Property unter dem erwarteten Namen, nimmt der Bot die erste URL-Property. Beim Start steht im Log, welche Properties verwendet werden.

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

Railway baut aus `requirements.txt` und startet `python main.py`. Die Python-Version steht in `.python-version`. Nach dem Umstieg auf Claude:

1. `ANTHROPIC_API_KEY` und `ALLOWED_USER_IDS` als Variablen ergänzen
2. `OPENAI_API_KEY` kann entfernt werden
