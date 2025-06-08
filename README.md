🧠 TOMIC – Tactical Option Modeling & Insight Console
TOMIC is jouw persoonlijke handelsassistent voor het vinden van de beste optietrades op basis van:

📈 Marketdata (spot, IV, skew, HV, ATR)

💼 Portfolio-fit (Greeks, margin)

🧠 TOMIC-strategie (PoS, EV, diversificatie)

📓 Journaling (entry, exit, risk)

Geen automatische trading – TOMIC ondersteunt, jij beslist.

⚙️ Functies
Feature	Beschrijving
📡 Marktdata ophalen	Spotprijs, IV-metrics, skew en option chains per symbool
📊 Portfolio-analyse	Gebaseerd op je huidige posities en Greeks
🎯 Strategie-selectie	Maximaal 5 kansen volgens TOMIC-score
✍️ Journal-integratie	Met exit-signalen, EV, PoS, risico en entrylogica
📁 Exporteerbaar	CSV/JSON-export voor eigen dashboards of analyse

🚀 Starten
Installeer vereisten
pip install -r requirements.txt

Start TWS / IB Gateway

Zorg dat TWS actief is op poort 7497.

Test de verbinding
python tests/test_ib_connection.py

Run control panel (interactief)
python tomic/cli/controlpanel.py

📂 Projectstructuur
tomic/
├── api/               # IB-connectie, accountdata, marketdata
├── analysis/          # Strategieanalyse, PoS, EV, Greeks
├── cli/               # Command line interfaces (bv. controlpanel)
├── core/              # Kernlogica en datamodellen
├── journal/           # Entry/exitregels, journaling
├── helpers/           # Utilities
├── proto/             # Job-definities (geen IBKR)
├── ibapi/             # Lokale TWS API (met protobuf)
tests/                 # Pytest-modules

✅ Tests
Run alle basistests met:
pytest tests/