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
De gebruiker geeft het symbool op (bijv. SPY). Er wordt gecontroleerd of het symbool geldig is (alfanumeriek, geen rare tekens).

2. Initialiseren van client en verbinding met IB
Er wordt een nieuwe OptionChainClient geïnitialiseerd. Deze verbindt met Interactive Brokers (TWS of IB Gateway) via host/port/client ID uit de config.
Na verbinding wordt gecontroleerd of de markt momenteel geopend is:
- Via reqContractDetails() worden de handelsuren opgehaald.
- Met reqCurrentTime() en is_market_open() wordt bepaald of now binnen deze uren valt.
- De data type wordt ingesteld (realtime of frozen) op basis van marktstatus.
📌 Extra logica: tijdzone van de markt wordt uit contractDetails.timeZoneId gehaald en meegegeven aan alle tijdsberekeningen.

3. Spot price ophalen
De actuele spotprijs wordt opgevraagd met reqMktData() voor het onderliggende aandeel.
Indien geen geldige ticks worden ontvangen binnen de timeout, wordt een fallback gebruikt: fetch_volatility_metrics() (webscrape).
📌 Snapshot fallback (data_type = 2) wordt automatisch gebruikt als de markt gesloten is.

4. ContractDetails ophalen voor de underlying
De unieke conId, tradingClass, en primaryExchange worden opgehaald via reqContractDetails() op het STK-contract.
Deze informatie wordt later hergebruikt bij het opbouwen van optiecontracten.

5. Optieparameters ophalen met reqSecDefOptParams()
Zodra de conId bekend is én een spotprijs beschikbaar is, worden optieparameters opgehaald:
- Verkrijgbaar via securityDefinitionOptionParameter()
- Bevat alle mogelijke expiries en strikes.
Er wordt gefilterd op basis van: Minimale DTE (bijv. 15 dagen), Aantal reguliere en wekelijkse expiries (bijv. 3 + 4) en Strike-afstand tot spot (±10 punten of uit config)

📌 Deze stap kan falen als de spotprijs niet tijdig beschikbaar is.

6. Selectie van relevante expiries en strikes
De gegenereerde expiries en strikes worden gefilterd en gelogd:
- Alleen strikes binnen het opgegeven bereik rond de spotprijs.
- Expiries worden ingedeeld in weeklies en maandelijkse (third Friday).
- Het totaal aantal optiecombinaties wordt berekend.

7. Bouwen van optiecontracten en opvragen van contractdetails
Voor elke combinatie van expiry × strike × {Call, Put} wordt een OptionContract opgebouwd en reqContractDetails() aangeroepen.
Een Semaphore beperkt het aantal parallelle verzoeken (bijv. 5 tegelijk).

📌 Als USE_HISTORICAL_IV_WHEN_CLOSED actief is, worden Greeks overgeslagen en wordt enkel IV via fetch_historical_iv() ingevuld.

8. Callback op contractDetails() voor elke optie
Zodra contractdetails zijn ontvangen voor een optiecontract, wordt direct reqMktData() gestuurd om live of snapshot data (bid/ask/Greeks) op te halen.
De contractinfo wordt gelogd en opgeslagen.

📌 Dezelfde data_type wordt gebruikt als succesvol was bij spot price (1=realtime, 2=frozen).

9. Ontvangen van market data (Greeks, bid/ask) en filtering
In deze stap wordt alle inkomende marktdata verzameld en opgeslagen:
- Greeks: IV, Delta, Gamma, Vega, Theta
- Prijzen: Bid, Ask, Close
- Open Interest & Volume

Contracten met delta buiten bereik (DELTA_MIN en DELTA_MAX) worden gemarkeerd als ongeldig.
Verzoeken zonder geldige data worden herhaald volgens OPTION_DATA_RETRIES, met een timeout per poging (BID_ASK_TIMEOUT).

10. Exporteren van CSV-bestanden en verbreken van verbinding
Na ontvangst van alle data:
- De verbinding met IB wordt netjes verbroken.
- CSV-bestanden worden geschreven naar exports/YYYYMMDD/option_chain_<symbol>_<timestamp>.csv en other_data_<symbol>_<timestamp>.csv.
- Parity deviation wordt berekend voor call/put-paren rond de eerste expiry.

📌 Bij onvolledige data wordt alsnog geëxporteerd wat beschikbaar is.

11. (Fallback) Berekenen van term structure als webscrape faalt
Als term_m1_m2 of term_m1_m3 ontbreekt in de webscrape (stap 3), dan wordt deze alsnog berekend op basis van de ontvangen IVs rond de spotprijs per expiry.





✅ Tests
Run alle basistests met:
pytest tests/