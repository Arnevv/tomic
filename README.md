🧠 TOMIC – Tactical Option Modeling & Insight Console

TOMIC is jouw persoonlijke handelsassistent voor het vinden van de beste optietrades op basis van:
📈 Marketdata (spot, IV, skew, HV, ATR)
💼 Portfolio-fit (Greeks, margin)
🧠 TOMIC-strategie (PoS, EV, diversificatie)
📓 Journaling (entry, structured exit rules, risk)

Geen automatische trading – TOMIC ondersteunt, jij beslist.

⚙️ Functies
Feature	Beschrijving
📡 Marktdata ophalen	Spotprijs, IV-metrics, skew en option chains per symbool
📊 Portfolio-analyse	Gebaseerd op je huidige posities en Greeks
🎯 Strategie-selectie	Maximaal 5 kansen volgens TOMIC-score over meerdere expiraties binnen DTE-bereik
✍️ Journal-integratie	Met exit-signalen, EV, PoS, risico en entrylogica
📁 Exporteerbaar	CSV/JSON-export voor eigen dashboards of analyse
📲 Theoretical value calculator  Bereken optiewaarde en edge t.o.v. midprice

🚀 Starten
Installeer vereisten
pip install -r requirements.txt

Synchroniseer sluitingsdata
python tomic/cli/fetch_prices.py

Controleer datasetkwaliteit
python tomic/cli/csv_quality_check.py path/to/option_chain.csv

Run control panel (interactief)
python tomic/cli/controlpanel.py

📁 DATA & MARKTDATA
1. OptionChain importeren (CSV)
2. OptionChain ophalen via Polygon API
3. Controleer CSV-kwaliteit
4. Run GitHub Action lokaal
5. Backfill historical_volatility obv spotprices
6. Fetch Earnings

7. Terug

Wat doet elk item?
Optie Beschrijving
1. OptionChain importeren (CSV)    Importeert een eerder geëxporteerde option chain (bijv. van Polygon of een interne batch) en normaliseert de data voor EOD-gebruik.
2. OptionChain ophalen via Polygon API    Roept fetch_polygon_option_chain(symbol) aan en slaat option chain info op (nu nog in ontwikkeling).
3. Controleer CSV-kwaliteit    Valideert een lokaal CSV-bestand met chaindata: kolommen, lege velden, duplicaten enz.
4. Run GitHub Action lokaal    Start fetch_prices_polygon en commit/pusht wijzigingen.
5. Backfill historical_volatility obv spotprices    Berekent HV op basis van lokale spotprijzen.
6. Fetch Earnings    Haalt earnings data op via Alpha Vantage API.
7. Terug    Keert terug naar het hoofdmenu.

📊 ANALYSE & STRATEGIE
1. Trading Plan
2. Portfolio ophalen en tonen
3. Laatst opgehaalde portfolio tonen
4. Toon portfolio greeks
5. Toon marktinformatie
6. Chainbron kiezen

Wat doet elk item?
Optie Beschrijving
1. Trading Plan    Open het "TOMIC Trading Plan"-overzicht.
2. Portfolio ophalen en tonen    Haal actuele posities op en toon het strategie-dashboard.
3. Laatst opgehaalde portfolio tonen    Gebruik eerder opgeslagen portfolio-data.
4. Toon portfolio greeks    Laat delta, gamma, vega en theta van je posities zien.
5. Toon marktinformatie    Geeft IV- en HV-metrics weer voor je standaard-symbolen en toont de eerstvolgende earningsdatum. Voer 999 in om een Polygon-scan te starten die alle symbolen scoort en de topresultaten toont (aantal instelbaar via MARKET_SCAN_TOP_N).
6. Chainbron kiezen    Selecteer een option chain via Polygon of een eigen CSV-export.

Kies je voor **Chainbron kiezen**, dan kun je eerst bepalen waar de keten vandaan
komt. Na het laden filtert de *StrikeSelector* op DTE, delta en overige regels
uit `strike_selection_rules.yaml`. Voor de overblijvende opties worden edge,
ROM, EV en PoS berekend. De top vijf wordt getoond en je kunt de complete lijst
exporteren.

### EOD-analyseflow: close → scoring → review

Het controlpanel werkt nu volledig op end-of-day data en begeleidt je door drie
duidelijke stappen zodra je een voorstel bekijkt:

1. **Close-refresh** – de CLI laadt de meest recente sluitingsprijzen uit
   `PRICE_HISTORY_DIR` en vult ontbrekende mids aan met close-data. Config voor
   live TWS-verbindingen is niet langer nodig.
2. **Herberekening** – ROM, PoS, EV, max loss, scenario's en acceptance
   criteria worden opnieuw doorgerekend op basis van deze sluitingsdata. Wanneer
   de acceptatieregels niet meer gehaald worden, stopt de flow en toont de CLI de
   onderliggende redenen.
3. **Review & export** – alleen wanneer de criteria nog geldig zijn, verschijnt
   de vraag of je het voorstel wilt bewaren. In plaats van concept-orders naar
   TWS te sturen maak je nu een CSV/JSON-export en werk je je journal bij.

Exports worden geplaatst onder `exports/tradecandidates/YYYYMMDD/` met de naam
`trade_candidates_<symbol>_<strategy>_<expiry>_<HHMMSS>.csv`.

Elke strategie-evaluatie logt nu ook de gebruikte legs. De logregel toont de
expiratie en per leg het type en de strike, bijvoorbeeld
`expiry=2025-01-01 | SC=110C | LC=120C | SP=90P | LP=80P`. Deze volgorde komt
overeen met de rijen in het bijbehorende `trade_candidates_*.csv`-bestand,
zodat je eenvoudig kunt terugvinden welke combinatie tot een bepaald logresultaat
leidde.

Krijg je geen voorstellen, dan toont TOMIC nu ook hoeveel combinaties zijn
afgewezen door een ratioscheck of risicocriteria. Zo weet je direct waarom er
geen strategie werd gevonden.

Wil je exact zien welke regels kandidaten uitsloten? Start de analyse met
`--show-filter-stats` of zet de omgevingsvariabele `EXPLAIN_FILTERS=true`.
TOMIC meldt dan per filter hoeveel combinaties zijn afgevallen:

```
$ tomic analysis --show-filter-stats
min_rom            : 12
delta_range        : 8
market_data.volume : 3
```

Blijkt een regel te streng, pas dan de waarden in `criteria.yaml` of
`tomic/strike_selection_rules.yaml` aan en valideer ze via `tomic rules
validate <pad/naar/criteria.yaml> --reload`.

Bij onvoldoende volume of open interest toont de log nu per strike ook volume,
open interest en expiratie in de vorm `strike [volume, open interest, expiry]`.

⏳ Data-verversing
Plan een dagelijkse job (of gebruik `tomic/cli/fetch_prices.py`) om sluitingsdata
en IV-samenvattingen op te halen voordat je voorstellen beoordeelt. Wanneer de
bestanden jonger zijn dan één handelsdag blijft de UI in "preview"-modus; oudere
data wordt expliciet als verouderd gelabeld zodat je weet dat een nieuwe close-run
nodig is.

📂 Projectstructuur
tomic/
├── api/               # IB-connectie, accountdata, marketdata
├── analysis/          # Strategieanalyse, PoS, EV, Greeks
├── cli/               # Command line interfaces (bv. controlpanel)
├── core/              # Kernlogica en datamodellen
├── journal/           # Entry/exitregels, journaling
├── helpers/           # Utilities
├── ibapi/             # Lokale TWS API (met protobuf)
tests/                 # Pytest-modules

📄 Configuratie
Volatiliteitsdata wordt bewaard in JSON-bestanden onder `tomic/data`.
Belangrijke mappen in `config.yaml`:

- `PRICE_HISTORY_DIR`
- `IV_HISTORY_DIR`
- `IV_DAILY_SUMMARY_DIR`
- `HISTORICAL_VOLATILITY_DIR`
- `EARNINGS_DATES_FILE`

🔣 Symbolenbeheer
De standaard symbolen voor scripts en tests staan in `config/symbols.yaml`. Dit
bestand bevat een eenvoudige YAML-lijst met tickers:

```yaml
- AAPL
- MSFT
- SPY
```

Functies die `cfg_get("DEFAULT_SYMBOLS")` aanroepen vallen terug op deze lijst.
Pas het bestand handmatig aan of gebruik `tomic.config.save_symbols()` om de
inhoud programmatic te wijzigen.

Het bestand `earnings_dates.json` bevat verwachte earnings per symbool. De optie "Toon marktinformatie" gebruikt dit om de eerstvolgende datum te tonen.
Het bestand `tomic/data/earnings_data.json` bevat enkel metadata (bijv. laatste fetch-tijdstempel per symbool) en is niet nodig voor runtime-functies.

Dagelijkse prijsdata wordt met `tomic/cli/fetch_prices.py` opgehaald en in
`PRICE_HISTORY_DIR` opgeslagen. De standaard-lookback bedraagt twee jaar
(`PRICE_HISTORY_LOOKBACK_YEARS=2`, goed voor ~504 handelsdagen), maar je kunt dit
via `config.yaml` of een omgevingsvariabele verhogen naar bijvoorbeeld vijf jaar
voor circa 1.260 handelsdagen uit Polygon.

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

Voor strategie-specifieke instellingen gebruik je `config/strategies.yaml`. Hier kun je per strategie of voor alle strategieën via `default` extra opties zetten. `allow_unpriced_wings: true` zorgt er bijvoorbeeld voor dat long-legs zonder `mid`, `model` of `delta` toch geaccepteerd worden.


EOD-dataflow – Technische Documentatie
1. **Symboolinvoer**
   - Valideer tickers via `symbol.replace(".", "").isalnum()` voordat je
     bestanden aanmaakt.
   - Alle stappen loggen een ✅ met het symbool zodat je runs kunt auditen.

2. **Close- en spotdata laden**
   - `tomic/helpers/price_utils._load_latest_close` zoekt in
     `PRICE_HISTORY_DIR` en retourneert `(prijs, datum, bron)`.
   - Bij ontbrekende data wordt een duidelijke fout gelogd zodat je de
     fetch-scripts opnieuw kunt draaien (`tomic/cli/fetch_prices.py`).

3. **Optieketen prepareren**
   - `tomic/services/chain_processing.load_and_prepare_chain` normaliseert
     CSV-ketens, houdt de `close`-kolom intact en markeert elke optie met
     `mid_source="close"` wanneer alleen sluitingsdata beschikbaar is.
   - Fallback-strikes worden gesampled rond spot met behulp van de
     configuratie (`FIRST_EXPIRY_MIN_DTE`, `STRIKE_RANGE`, enz.).

4. **MidResolver & scoring**
   - `tomic/mid_resolver.MidResolver` vult mids op basis van close, parity en
     modellogica. Omdat er geen intraday refresh meer is, blijven alle
     voorstellen in "preview" totdat er een nieuwe close-run draait.
   - `tomic/analysis/scoring.validate_leg_metrics` accepteert voorstellen die
     voldoen aan de criteria en geeft anders een reden terug.

5. **Portfolio- en marktsnapshots**
   - `tomic/services/market_snapshot_service.MarketSnapshotService` combineert
     IV-samenvattingen, HV-reeksen en earnings-data tot één factsheet.
   - Portfolio-overzichten gebruiken dezelfde close-data en tonen badges zodra
     datasets ouder zijn dan één handelsdag.

6. **Exports & journaling**
   - CSV/JSON-exports landen onder `exports/tradecandidates/YYYYMMDD/`.
   - `tomic/journal` gebruikt dezelfde EOD-metadata om entries van context te
     voorzien (spot, IV, earnings, acceptance-resultaat).

✅ Tests
Run alle basistests met:
pytest tests/

🔍 Debugging
Om de volledige Polygon API-sleutel te loggen, zet je de omgevingsvariabele `TOMIC_SHOW_POLYGON_KEY=1` voordat je scripts start. De sleutel wordt dan niet gemaskeerd.

📐 Rules configuratie beheren
Met de ingebouwde CLI kun je de regels in `criteria.yaml` veilig aanpassen. Via het configuratiemenu
van het control panel is hiervoor het submenu **Strategie & Criteria** toegevoegd:

```
=== Strategie & Criteria ===
1. Optie-strategie parameters
2. Criteria beheren
3. Terug
```

Kies **Criteria beheren** om de regels te bekijken, valideren of te herladen:

```
=== Criteria beheren ===
1. Toon criteria
2. Valideer criteria.yaml
3. Valideer & reload
4. Reload zonder validatie
5. Terug
```

Vanuit het menu kun je tevens de regels valideren en desgewenst services herladen.

```bash
# Toon de actuele configuratie
tomic rules show

# Valideer wijzigingen en herlaad services
tomic rules validate path/naar/criteria.yaml --reload
```

Meer voorbeelden en uitleg staan in `docs/rules_cli.md`.
