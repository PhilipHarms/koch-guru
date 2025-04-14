# 🧠 KochGuru

**KochGuru** ist ein Telegram-Bot, der auf deine Nachrichten reagiert, passende Rezepte aus meiner Notion-Datenbank vorschlägt und dir hilft, deine Kochwoche zu planen.

## ✨ Features

- 🔗 Verbindung mit meiner Notion-Rezeptdatenbank
- 💬 ChatGPT-gestützte Dialoge ("Was sollen wir kochen?")
- 🧠 Interpretation von Feedback wie "nur vegetarisch" oder "wir haben noch Brokkoli"
- ✅ Markierung von Rezepten als "Cook this Week"
- 🛒 Erweiterbar: Einkaufsliste, PDF-Wochenplan, ...

## 🛠 Setup

```bash
git clone https://github.com/PhilipHarms/koch-guru.git
cd koch-guru
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt