# 🧠 KochGuru

KochGuru ist ein privater Telegram-Bot, der Rezepte aus einer Notion-Rezeptdatenbank vorschlägt. Die Auswahl trifft Claude (über OpenRouter), aber ausschließlich aus den Rezepten in Notion.

Dazu entsteht eine Web-App (installierbar auf dem Handy), die auf derselben Datenbank aufbaut. Bot und Web-App laufen in einem Prozess und teilen sich Notion-Zugriff und Zwischenspeicher. Stand: Anmeldung per persönlichem Link, die Schnittstelle unter `/api` und die Rezeptübersicht (Suche, Filter, Kacheln und Liste) sind fertig. Heute, Woche und Einkauf folgen.

## Was der Bot kann

- Freitext verstehen: „was Schnelles, vegetarisch“, „wir haben noch Brokkoli und Feta“, „Ideen für die Woche“
- Bis zu vier passende Rezepte mit Link und kurzer Begründung vorschlagen, oder ehrlich sagen, dass nichts passt
- Rückfragen verstehen („lieber ohne Fleisch“, „noch was anderes“); der Verlauf gilt pro Chat und wird nach zwei Stunden Pause oder mit `/neu` vergessen
- Wochenliste: 📅 unter einem Vorschlag setzt die Checkbox „This Week?“ in Notion, ✅ nimmt sie wieder raus
- `/woche`: Wochenliste anzeigen, `/woche_leeren`: alle Häkchen entfernen
- Rezepte per Link anlegen: Link schicken, Vorschau prüfen, „Speichern“ legt die Seite in Notion an (Name, Link, passende Tags aus den bestehenden, Titelbild, Zutaten und Zubereitung im Seiteninhalt). Ist der Link schon in der Sammlung, sagt der Bot das. Seiten, die ihren Inhalt erst per JavaScript laden (Instagram, TikTok), kann er nicht lesen.
- Rezepte per Foto anlegen: Foto einer Kochbuchseite, eines Zeitschriftenrezepts oder Screenshots schicken, gern mehrere Fotos als Album. Claude liest das Rezept ab, wählt Tags und, wenn erkennbar, das Kochbuch aus den bestehenden „Origin“-Einträgen. Die Originalfotos werden an die Notion-Seite gehängt.
- Importierte Rezepte bekommen ein passendes Emoji als Icon.
- `/zufall`: vier zufällige Rezepte
- `/aktualisieren`: Rezepte sofort neu aus Notion laden (sonst alle 5 Minuten automatisch)

Geplant: Zutaten-Verknüpfung beim Import, „Zuletzt gekocht“ und Zubereitungszeit (erst testweise für einzelne Rezepte).

## Aufbau

```
main.py                     Einstiegspunkt (Railway startet `python main.py`): Web-App plus Bot
koch_guru/
  server.py                 Startet Web-Server und Bot gemeinsam und beendet beide sauber
  core.py                   Gemeinsame Clients: Notion, Rezept-Repository, OpenRouter, HTTP
  config.py                 Umgebungsvariablen lesen und prüfen
  models.py                 Recipe-Datenklasse
  notion_repo.py            Notion-Zugriff: Datenquelle, Property-Mapping, Pagination, Cache
  llm.py                    OpenRouter-Client mit Structured Output
  services/recommend.py     Prompt, Auswahl und Validierung der Empfehlungen
  services/conversation.py  Kurzzeit-Gesprächsverlauf pro Chat (im Speicher)
  services/importer.py      Rezept aus einer URL (schema.org/JSON-LD, sonst Seitentext) oder von Fotos lesen
  services/drafts.py        Import-Entwürfe bis „Speichern“ oder „Verwerfen“ (im Speicher)
  bot/app.py                Telegram-Anwendung, Zugriffsschutz, Fehlerbehandlung
  bot/handlers.py           Befehle und Nachrichten
  bot/render.py             Telegram-HTML mit Escaping
  web/app.py                FastAPI: Anmeldung, Fehlerbehandlung, später die gebaute Oberfläche
  web/api.py                JSON-Schnittstelle unter /api
  web/auth.py               Anmeldung per persönlichem Link (Cookie)
  web/keys.py               Erzeugt Anmeldeschlüssel für APP_USERS
tests/                      Tests ohne Netzwerkzugriff
web/                        Oberfläche: Preact + TypeScript, gebaut mit Vite
  src/styles/tokens.css     Farben, Schrift, Abstände aus dem Design-System KochGuru (nicht von Hand ändern)
  src/styles/components.css Komponenten aus dem Design-System
  src/pages/                Bildschirme (Rezepte, Platzhalter für Heute, Woche, Einkauf)
  public/                   Manifest, App-Icons, Service Worker
  dist/                     Gebaute Oberfläche, die der Server ausliefert (eingecheckt, siehe unten)
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
| `APP_USERS` | für die Web-App | Wer sich anmelden darf, als `name:schlüssel`, mehrere mit Komma. Erzeugen mit `python -m koch_guru.web.keys philip charlotte`. Leer: Niemand kann sich anmelden, der Bot läuft trotzdem. |
| `PORT` | nein | Port des Web-Servers, Standard 8000. Railway setzt ihn selbst. |
| `OPENROUTER_MODEL` | nein | Modell-Slug bei OpenRouter, Standard `anthropic/claude-sonnet-5.5` |
| `RECIPE_CACHE_SECONDS` | nein | Standard 300 |
| `NOTION_PROP_LINK`, `NOTION_PROP_TAGS`, `NOTION_PROP_ORIGIN`, `NOTION_PROP_INGREDIENTS`, `NOTION_PROP_THIS_WEEK` | nein | Property-Namen, Standard `Link`, `Tags`, `Origin`, `Ingredients`, `This Week?` |

Die Titel-Property wird automatisch erkannt. Fehlt die Link-Property unter dem erwarteten Namen, nimmt der Bot die erste URL-Property. Beim Start steht im Log, welche Properties verwendet werden.

## Notion-Integration

- **Zutaten:** `Ingredients` ist eine Verknüpfung zu einer eigenen Zutaten-Datenbank. Damit der Bot die Zutatennamen lesen kann, muss auch diese Datenbank mit der Integration verbunden sein (Datenbank öffnen › ••• › Connections). Ohne Zugriff lädt der Bot die Rezepte ohne Zutaten und schreibt einen Hinweis ins Log.
- **Wochenliste:** Zum Setzen der Checkbox braucht die Integration die Berechtigung „Update content“.
- **Link- und Foto-Import:** Zum Anlegen neuer Rezepte und Hochladen der Fotos braucht sie „Insert content“.

Die eigene Telegram-ID findest du, indem du dem Bot schreibst, solange `ALLOWED_USER_IDS` leer ist.

## Web-App: Anmeldung und Schnittstelle

Jede Person hat einen eigenen Anmeldelink `https://<adresse>/login/<schlüssel>`. Einmal pro Gerät öffnen, danach bleibt man ein Jahr angemeldet (HTTP-only-Cookie). Um ein Gerät abzumelden, den Schlüssel in `APP_USERS` austauschen.

| Methode und Pfad | Zweck |
| --- | --- |
| `GET /api/me` | Wer angemeldet ist |
| `GET /api/recipes` | Alle Rezepte mit Tags, Origin, Zutaten, Emoji, Foto und Wochenstatus |
| `GET /api/recipes/{id}` | Ein Rezept |
| `GET /api/recipes/{id}/content` | Inhalt der Notion-Seite: Zeit, Portionen, Zutaten mit Mengen, Schritte und alles Weitere |
| `GET /api/recipes/{id}/image` | Titelbild der Notion-Seite, über den Server gereicht, damit das Handy es zwischenspeichern kann |
| `PATCH /api/recipes/{id}` | `{"this_week": true}` setzt oder entfernt das Rezept auf der Wochenliste |
| `POST /api/week/clear` | Wochenliste leeren |
| `POST /api/suggest` | `{"wish": "…", "history": […]}`: Rezeptideen von Claude aus der eigenen Sammlung, wie im Bot |
| `GET /healthz` | Lebenszeichen ohne Anmeldung |

Ohne gültiges Cookie antworten alle `/api`-Aufrufe mit 401. Fehler von Notion kommen als 502, Überlastung (429 bei Notion) als 503 mit `Retry-After`.

## Lokal starten

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # Werte eintragen
python main.py          # Web-App auf http://localhost:8000 plus Bot
python -m koch_guru.bot # nur der Bot
pytest
```

Lokal anmelden: `http://localhost:8000/login/<schlüssel aus APP_USERS>`.

### Oberfläche entwickeln

```bash
cd web
npm install
npm run dev     # http://localhost:5173, leitet /api und /login an python main.py weiter
npm run build   # prüft die Typen und baut nach web/dist
```

Der Server liefert `web/dist` aus. Solange Railway nur Python baut, wird `web/dist` mit eingecheckt: Nach Änderungen an der Oberfläche `npm run build` ausführen und `web/dist` mit committen. Später übernimmt ein Docker-Build diesen Schritt.

Wichtig: Läuft der Bot gleichzeitig auf Railway, verteilt Telegram die Nachrichten zufällig auf beide Instanzen (Fehler „terminated by other getUpdates request“). Lokal daher am besten mit einem zweiten Test-Bot-Token arbeiten.

## Deployment auf Railway

Railway baut aus `requirements.txt` und startet `python main.py`. Die Python-Version steht in `.python-version`. Benötigte Variablen: `TELEGRAM_TOKEN`, `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `OPENROUTER_API_KEY`, `ALLOWED_USER_IDS` und für die Web-App `APP_USERS`.

Damit die Web-App erreichbar ist, braucht der Dienst eine öffentliche Adresse: in Railway unter Settings › Networking › „Generate Domain“. Railway setzt `PORT` selbst und leitet HTTPS an den Server weiter.

Im OpenRouter-Dashboard erscheinen die Anfragen unter dem App-Namen „KochGuru“.
