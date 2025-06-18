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

Zorg dat TWS actief is op poort 7497 voor paper trading of 7496 voor live trading.

Test de verbinding
python tests/test_ib_connection.py

Run control panel (interactief)
python tomic/cli/controlpanel.py

⏳ Verbindingstips
Wacht na het verbinden tot de callback `nextValidId()` is aangeroepen voordat
je verzoeken naar TWS stuurt. Pas dan is de client klaar om orders of
marktdata-opvragingen te verwerken.

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
Dagelijkse prijsdata wordt met `tomic/cli/fetch_prices.py` tot maximaal 252 dagen
terug opgehaald en in deze database opgeslagen.

Alle configuratiefuncties gebruiken een interne lock. Zowel lezen via
``config.get()`` als schrijven met ``update()`` of ``reload()`` is hierdoor
gesynchroniseerd en veilig vanaf meerdere threads.

Deel je een `MarketClient`-instantie tussen taken? Gebruik de interne
  `data_lock` (``threading.RLock``) om toegang tot ``market_data`` te beveiligen
  en om invalidatie-timers in sync te houden. De gewone ``_lock`` blijft nodig
  om IB-aanroepen te serialiseren en wordt automatisch gebruikt door de async
  helpers. Voorbeeld:

  ```python
  with client.data_lock:
      price = client.spot_price
  ```

De functies ``await_market_data`` en ``compute_iv_term_structure`` nemen
deze lock intern over. Ze kunnen daardoor veilig vanuit meerdere threads
worden aangeroepen. Andere helpers zoals ``export_csv`` verwachten dat je
zelf de verbinding verbreekt of de lock houdt tijdens het wegschrijven van
data.

Extra opties in `config.yaml`:
- `USE_HISTORICAL_IV_WHEN_CLOSED`: gebruik historische IV wanneer de markt
  gesloten is. De optieketen wordt dan opgebouwd met `reqHistoricalData` in
  plaats van `reqMktData`.
- `INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN`: voeg Greek-gegevens alleen toe als de
  markt open is.


📋 Stappenplan data ophalen
1. Invoer van symbool
2. Initialiseren client + verbinden met IB
3. Spot price ophalen
4. ContractDetails ophalen voor STK
5. reqSecDefOptParams() voor optieparameters
6. Selectie van relevante expiries + strikes
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