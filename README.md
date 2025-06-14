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

⏳ Verbindingstips
Wacht na het verbinden tot de callback `nextValidId()` is aangeroepen voordat
je verzoeken naar TWS stuurt. Pas dan is de client klaar om orders of
marktdata-opvragingen te verwerken.

- Stel bovendien exchange correct in:
  `contract.exchange = "SMART"` of de gewenste beurs.
- Voor spotprijzen probeert TOMIC eerst `reqMarketDataType(1)` (live) en
  valt zo nodig terug naar `reqMarketDataType(2)` (frozen) en daarna
  `reqMarketDataType(3)` (delayed). Optieprijzen worden direct met
  `reqMarketDataType(3)` (delayed) aangevraagd.
- Optieketen selectie: de eerste 4 expiries en strikes binnen ±50 punten van de
  afgeronde spotprijs (aanpasbaar via `STRIKE_RANGE`). Opties met een delta
  buiten de grenzen `DELTA_MIN` en `DELTA_MAX` worden genegeerd.

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

📄 Configuratie
De locatie van de volatiliteitsdatabase wordt ingesteld via `VOLATILITY_DB` in
`config.yaml`. Standaard wijst dit naar `data/volatility.db`.
Dagelijkse prijsdata wordt met `tomic/cli/fetch_prices.py` tot maximaal 90 dagen
terug opgehaald en in deze database opgeslagen.


📋 Stappenplan data ophalen
1. Invoer van symbool
2. Initialiseren client + verbinden met IB
3. Spot price ophalen
4. ContractDetails ophalen voor STK
5. reqSecDefOptParams() voor optieparameters
6. Selectie van relevante expiries + strikes (binnen ±50 pts spot)
7. Per combinatie optiecontract bouwen en reqContractDetails()
8. Callback: contractDetails() voor opties
9. Ontvangen van market data (bid/ask/Greeks) en filteren op delta
10. Na ontvangst van alle data wordt de verbinding verbroken en worden de CSV-
    bestanden weggeschreven
11. Ontbreekt de webscrape-term structure, dan wordt deze berekend uit de
    ontvangen IV's rond de spotprijs


✅ Tests
Run alle basistests met:
pytest tests/