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
📲 Theoretical value calculator  Bereken optiewaarde en edge t.o.v. midprice

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
Volatiliteitsdata wordt bewaard in JSON-bestanden onder `tomic/data`.
Belangrijke mappen in `config.yaml`:

- `PRICE_HISTORY_DIR`
- `IV_HISTORY_DIR`
- `IV_DAILY_SUMMARY_DIR`
- `HISTORICAL_VOLATILITY_DIR`

Dagelijkse prijsdata wordt met `tomic/cli/fetch_prices.py` tot maximaal 252 dagen
terug opgehaald en in `PRICE_HISTORY_DIR` opgeslagen.

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
- `HIST_DURATION`: duurparameter voor `reqHistoricalData` (default `1 D`).
- `HIST_BARSIZE`: barSize voor `reqHistoricalData` (default `1 day`).
- `HIST_WHAT`: whatToShow voor sluitprijzen (default `TRADES`).
- `MKT_GENERIC_TICKS`: ticklijst voor `reqMktData` wanneer snapshots niet
  worden gebruikt (default `100,101,106`).
- `INCLUDE_GREEKS_ONLY_IF_MARKET_OPEN`: voeg Greek-gegevens alleen toe als de
  markt open is.
- `IV_TRACKING_DELTAS`: lijst van deltawaarden voor IV-historie (default `[0.25, 0.5]`).
- `IV_EXPIRY_LOOKAHEAD_DAYS`: doelen voor expiries in dagen (default `[0, 30, 60]`).


Stappenplan Data Ophalen – Technische Documentatie
1. Invoer van symbool
Valideer symbool via:
symbol.replace(".", "").isalnum()
Log: ✅ [stap 1]
Functie: export_option_chain()

2. Initialiseren van client en verbinden met IB
Client: OptionChainClient(symbol)
Verbinding via start_app():
Host, port en client ID uit config (IB_HOST, IB_PORT, IB_CLIENT_ID)
Timeout connectie: 5s
Bepaal marktstatus:
reqContractDetails() → wacht maximaal 5s
reqCurrentTime() → wacht maximaal 5s
Marktstatus via is_market_open() met liquidHours en ZoneInfo(timeZoneId)
Succesvolle marketdata type wordt ingesteld:

reqMarketDataType(1) indien open, anders reqMarketDataType(2)

Methode: _init_market()

3. Spot price ophalen
reqMktData() op STK-contract

Wacht op eerste tick (TickTypeEnum.LAST, CLOSE, etc.)

Timeout: SPOT_TIMEOUT (default: 10s, uit config)

Bij geen tick: fallback via fetch_volatility_metrics()

Snapshot indien markt gesloten (use_snapshot = True)

Eventuele fallbackprijs wordt gelogd en opgeslagen

4. ContractDetails ophalen voor de underlying
reqContractDetails() op STK-contract

Timeout: 10s (hardcoded in details_event.wait(10))

Output: conId, tradingClass, primaryExchange (gebruikt in latere contracten)

Logging: ✅ [stap 4] ConId: ...

5. Optieparameters ophalen (reqSecDefOptParams())
Methode: securityDefinitionOptionParameter()

Vereisten: spotprijs moet beschikbaar zijn

Filters op:

FIRST_EXPIRY_MIN_DTE (default: 15, uit config)

AMOUNT_REGULARS, AMOUNT_WEEKLIES

STRIKE_RANGE of STRIKE_STDDEV_MULTIPLIER indien IV beschikbaar

Timeout: wacht tot params_event of option_params_complete
(OPTION_PARAMS_TIMEOUT, default 20s)

Fallback bij ontbreken IV: gebruik van ±STRIKE_RANGE

6. Selectie van relevante expiries en strikes
Expiries verdeeld in:

Maandelijks: _is_third_friday()

Weeklies: _is_weekly()

Strikes:

Rond spotprijs

Afstand obv STRIKE_STDDEV_MULTIPLIER × stddev (indien IV beschikbaar)

Logging:

✅ [stap 6] Geselecteerde strikes/expiries

expected_contracts = len(expiries) × len(strikes) × 2

7. Opbouw van optiecontracten + contractdetails
Elke combinatie expiry × strike × {Call, Put} → OptionContract

Per contract: reqContractDetails()

Retries: CONTRACT_DETAILS_RETRIES (default: 2)

Timeout: CONTRACT_DETAILS_TIMEOUT (default: 2s)

Maximaal MAX_CONCURRENT_REQUESTS tegelijk (default: 5)

Bij mislukking: gelogd als ❌, fallback = skip

Methode: _request_option_data()

8. Callback op contractDetails voor elke optie
Zodra contract is ontvangen:

reqMktData() met marketDataType gelijk aan stap 3

Bij gesloten markt: USE_HISTORICAL_IV_WHEN_CLOSED=True → fetch_historical_option_data() voor IV en close

Bid/ask/Greeks gestart indien live

Logging: ✅ [stap 8] reqMktData sent ...

9. Ontvangen van market data (Greeks, bid/ask)
Ticks verzameld in: tickPrice, tickOptionComputation, tickGeneric

Vereiste velden:

Open: bid, ask, iv, delta, gamma, vega, theta

Gesloten: alleen iv en close uit historische data

Filtering:

Contracts met delta buiten DELTA_MIN/DELTA_MAX worden ongeldig verklaard

Retries bij incomplete data:

Max: OPTION_DATA_RETRIES (default: 3)

Timeout per poging: BID_ASK_TIMEOUT (default: 10s)

Wacht tussen retries: OPTION_RETRY_WAIT

10. Exporteren van CSV’s en disconnect
Disconnect vóór het schrijven naar disk

CSV-bestanden:

option_chain_<symbol>_<timestamp>.csv

other_data_<symbol>_<timestamp>.csv met o.a. IV Rank, HV30, ATR14, VIX

Berekening parity deviation op eerste expiry

Exporteer ook bij incomplete data

Functies: _write_option_chain(), _write_metrics_csv()

11. (Fallback) Term structure berekenen
Als term_m1_m2 of term_m1_m3 ontbreekt in Barchart scrape, dan:

Berekening met gemiddelde IV’s rond spot (±TERM_STRIKE_WINDOW, default: 5)

Per expiry → mean IV → bereken M1-M2 en M1-M3

Functie: compute_iv_term_structure()






✅ Tests
Run alle basistests met:
pytest tests/

Notes from video:
