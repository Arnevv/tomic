# IV backfill – architectuur- en implementatieanalyse

## 1. Doel en uitgangspunten
* **Probleem.** De huidige `iv_daily_summary`-jsons bevatten slechts de meest recente Polygon-snapshot per ticker. Hierdoor ontbreekt historie (3-5 jaar) en ontstaan gaten op feestdagen zoals Columbus Day.
* **Doel.** Voeg in het "Data & Marktdata"-menu een IV-backfill workflow toe waarin de gebruiker een symbool en CSV-pad kiest, TOMIC een analyse + diff toont en de gebruiker daarna beslist of de records in `iv_daily_summary` worden weggeschreven.
* **Randvoorwaarden.**
  - Backfill mag geen bestaande data-corruptie veroorzaken; sortering, deduplicatie en consistentie met `historical_volatility` en `spot_prices` moeten gewaarborgd blijven.
  - De workflow moet veilig zijn voor symbols die al (gedeeltelijk) data bevatten.
  - Resultaten moeten downstream direct bruikbaar zijn voor market snapshots, strategie-aanbevelingen en rules.

## 2. Huidige data-architectuur (relevant voor backfill)
* `run_dataexporter()` beheert het "Data & Marktdata" menu en biedt nu exporteurs/kwaliteitschecks maar geen IV-import.【F:tomic/cli/controlpanel.py†L1026-L1105】
* `append_to_iv_summary()` schrijft individuele records naar `iv_daily_summary/<symbol>.json` en gebruikt `update_json_file()` voor dedupe + sorteer op datum.【F:tomic/analysis/vol_json.py†L46-L71】【F:tomic/journal/utils.py†L39-L58】
* `MarketSnapshotService` leest per symbool de laatste IV-samenvatting, historische volatiliteit en slotkoers om factsheets/overzichten te bouwen.【F:tomic/services/market_snapshot.py†L120-L163】
* `build_market_overview()` gebruikt IV- en HV-series om strategieaanbevelingen + iv_vs_hv-metrics te produceren.【F:tomic/analysis/market_overview.py†L60-L159】
* `fetch_polygon_iv30d()` levert de huidige dagrecord, inclusief `atm_iv` (0-1), `iv_rank`, `iv_percentile`, term structure en skew, en schrijft dit naar de JSON.【F:tomic/providers/polygon_iv.py†L852-L902】

### Implicaties
* Onze JSON-schema bevat geen ruwe `IV30`-percentages, moving averages of optievolume—die zitten in de nieuwe CSV-bron en moeten expliciet gemapt/opgeslagen worden.
* IV-rank/-percentile steunen op historische HV en prijsdata; als we oude IV toevoegen zonder bijbehorende HV/spot, verliezen we context voor strategie-aanbevelingen.

## 3. Geplande backfill-workflow
1. **Menu-integratie.** Voeg een item "IV backfill" aan `run_dataexporter()` toe. Het submenu moet het symbool vragen, de CSV-path laten selecteren en daarna een analyseflow starten.
2. **CSV-inleeslaag.**
   - Verwacht kolommen zoals `Date`, `IV30`, `IV30 20-Day MA`, `OHLC 20-Day Vol`, `OHLC 52-Week Vol`, `Options Volume`.
   - Parseer `Date` als `YYYY-MM-DD` (CSV date-formaat aanpassen waar nodig), converteer percentages naar fracties (`atm_iv = IV30 / 100`, `iv30_ma20 = (IV30 20-Day MA) / 100`).
   - Map realized volatilities (`OHLC 20-Day Vol`, `OHLC 52-Week Vol`) naar bestaande HV-files als `hv20`/`hv252` wanneer waarden aanwezig zijn, of registreer dat HV-data nodig is.
3. **Validatie en diff-rapport.**
   - Controleer op ontbrekende kolommen, lege rijen en dubbele data.
   - Vergelijk met bestaande `iv_daily_summary/<symbol>.json` records (bijv. datering, waardeverschillen) en toon: aantal nieuwe dagen, updates (verschillende waarden), overlappende data, hiaten.
   - Vergelijk datums met HV (`historical_volatility/<symbol>.json`) en spot (`spot_prices/<symbol>.json`) om te signaleren of ondersteunende data ontbreekt.
4. **Gebruikersbeslissing.** Na diff toont TOMIC een samenvattende tabel en vraagt bevestiging.
   - Bij bevestiging: schrijf in bulk. We kunnen `update_json_file()` per record gebruiken, maar efficiënter is een helper die records merge't en één keer wegschrijft (inclusief back-up van bestaande file).
   - Optioneel: schrijf ook HV/spot-data als de CSV deze bevat; anders markeer dat aanvullende backfill nodig is (zie §4).
5. **Logging & audit.** Log successen/mislukkingen, schrijf bij voorkeur naar CLI + logfile. Overweeg een `.bak` back-up voor de bestaande JSON alvorens te overschrijven.
6. **Dry-run/preview modus.** Bied een vlag om alleen een rapport te genereren zonder te schrijven (nuttig voor batchimporten of CI-checks).

## 4. Spot- en HV-consistentie
* `MarketSnapshotService` vereist dat IV-, HV- en spot-data allemaal aanwezig zijn voor dezelfde datum; ontbrekende onderdelen leiden tot ontbrekende regels in de snapshot.【F:tomic/services/market_snapshot.py†L124-L163】
* Acties:
  - **Spotdata:** Controleer of voor elke nieuwe IV-datum een slotkoers aanwezig is in `spot_prices/<symbol>.json`. Anders het fetch_prices-script laten draaien of de gebruiker hierop wijzen voordat de IV wordt toegevoegd.
  - **Historische volatiliteit:** Gebruik CSV-kolommen (`OHLC 20-Day Vol`, `OHLC 52-Week Vol`) om automatisch `hv20`/`hv252` bij te vullen, of flag dat `tomic/cli/compute_volstats` of Polygon-variant opnieuw moet worden uitgevoerd om HV te genereren.【F:tomic/analysis/vol_json.py†L46-L71】【F:tomic/providers/polygon_iv.py†L852-L902】
  - **Optievolume:** Bepaal of we dit meenemen (nieuw veld zoals `options_volume`) en waar downstream het gebruikt gaat worden (strategie scoring, QA dashboards?).

## 5. Schema-uitbreiding & mapping
| CSV-kolom              | Opslagveld (voorstel) | Type | Opmerkingen |
|------------------------|-----------------------|------|-------------|
| `Date`                 | `date`                | str  | ISO 8601 | 
| `IV30`                 | `atm_iv`              | float| Opslaan als fractie (0-1) voor consistentie met bestaande data |
| `IV30 20-Day MA`       | `iv30_ma20`           | float| Nieuw veld; gebruik fractie |
| `OHLC 20-Day Vol`      | `hv20`                | float| Kan HV-json bijwerken |
| `OHLC 52-Week Vol`     | `hv252`               | float| idem |
| `Options Volume`       | `options_volume`      | int  | Opslaan als integer voor latere analytics |

* Bereken aanvullende velden indien mogelijk: `iv_rank`/`iv_percentile` (via bestaande helper `_iv_rank`) en term structure, mits benodigde expiries/IVs beschikbaar zijn. Anders markeer als `None` en laat downstream logica hiermee omgaan (de UI en pipeline tolereren `None`).

## 6. Downstream-impact en QA
* **Market overview & strategy selection.** Nieuwe of gewijzigde IV-data beïnvloedt strategiekeuzes en criteria zoals `iv_vs_hv20`/`iv_rank`, dus we moeten regressietests draaien op `market_overview` en relevante CLI-scripts.【F:tomic/analysis/market_overview.py†L81-L159】
* **StrategyPipeline exports.** Strategieproposals bevatten `iv_rank`/HV-waarden; regressies rondom scoring en filters zijn nodig zodra historische IV wordt gebruikt.【F:tomic/services/strategy_pipeline.py†L594-L638】
* **Volatility rules.** Documenteer dat criteria in `volatility_rules.yaml` mogelijk herzien moeten worden als er meer complete IV-historie beschikbaar komt.
* **Automated tests.**
  - Voeg unit-tests toe voor de CSV-parser (formatvalidatie, conversie, diff). 
  - Voeg integratietest toe die een mock-CSV inleest, preview genereert en checkt dat `iv_daily_summary` + HV/spot-updates consistent worden geschreven.
  - Overweeg property-tests op monotoniciteit (bijv. dat `date` gesorteerd blijft, geen duplicaten).

## 7. Voorbereiding op historische implied volatility als primaire bron
* **Data-coverage.** Met een gevulde `iv_daily_summary` kunnen we per datum werken, niet enkel met het laatst bekende snapshot. Pas logic aan die alleen laatste IV leest (`get_latest_summary`) om ook tijdreeksen te ondersteunen waar nodig.【F:tomic/analysis/vol_json.py†L24-L43】
* **Pipeline-aanpassingen.**
  - Introduceer een service die historische IV ophaalt voor de gekozen analyseperiode (bijv. DTE-filter) en deze gebruikt voor scenario-analyses of fallback-prijzen wanneer `USE_HISTORICAL_IV_WHEN_CLOSED` actief is.【F:tomic/api/market_export.py†L635-L676】
  - Verrijk `StrategyProposal` met historische IV-statistieken (bijv. gemiddelde IV over vorige maand) naast huidige HV.【F:tomic/services/strategy_pipeline.py†L594-L638】
* **Criteria & scoring.** Met historische IV kunnen we drempels definieren zoals "IV boven 75e percentiel t.o.v. laatste 2 jaar" of "IV compressie t.o.v. 20-daags gemiddelde". Dit vereist:
  - Nieuwe metrics berekenen (IV percentile/ rank op basis van de backfilled dataset i.p.v. HV-proxy).
  - Aanpassen van `volatility_rules.yaml` om historische IV-criteria te ondersteunen (bijv. `iv_vs_iv_ma20`).
* **Spot/HV synchronisatie.** Zorg dat HV en spot-data voor dezelfde periode aanwezig zijn; anders zullen iv-rank berekeningen zoals in `fetch_polygon_iv30d()` incorrect blijven.【F:tomic/providers/polygon_iv.py†L852-L902】
  - Dagelijkse spotdata trek je op via `fetch_prices_polygon`. De lookback voor
    Polygon-balken is configureerbaar met `PRICE_HISTORY_LOOKBACK_YEARS`
    (standaard 2). Zet deze tijdelijk op 5 om een volledige vijfjaarsbackfill
    te genereren voordat je IV-geschiedenis aanvult.
* **Tooling.** Maak het mogelijk om historische IV te exporteren naar spreadsheets of visualiseren in CLI (grafiek/diff) voor strategische analyse.

## 8. Risico's & mitigaties
* **Schema-drift:** Nieuwe velden kunnen tooling breken dat het oude schema verwacht. Los dit op met compatibiliteitslagen (bijv. alleen toevoegen wanneer aanwezig, fallback in loader).
* **Datakwaliteit:** CSV's van verschillende bronnen kunnen afwijkingen hebben; bouw flexibele parsing + duidelijke foutenrapportage.
* **Performance:** Grote CSV's (5 jaar) kunnen duizenden records bevatten. Gebruik efficiënte parsing (bijv. `csv` module, streaming) en schrijf in één keer naar disk.
* **Gebruikerservaring:** Voorzie duidelijke instructies en confirmatie, plus een `--force` CLI-flag voor geautomatiseerde backfills.

## 9. Volgende stappen
1. Schrijf parser + validator + diff-rapport.
2. Integreer menu-entry met preview/confirm flow.
3. Voeg helpers toe voor bulk-merge + optionele HV/spot updates.
4. Werk documentatie en release-notes bij.
5. Bouw tests en voer regressies uit op market overview/strategy pipeline.
6. Plan vervolgsprint voor historische IV integratie (metrics, criteria, UI).
