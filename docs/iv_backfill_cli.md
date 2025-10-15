# IV backfill CLI-handleiding

Deze handleiding bouwt voort op de architectuur- en workflowanalyse in
[`docs/iv_backfill_analysis.md`](./iv_backfill_analysis.md). Waar de analyse
het "waarom" en "wat" toelicht, focust deze pagina op het dagelijks gebruik
van de interactieve CLI, inclusief bekende beperkingen en testdekking om
regressies te vermijden.

## 1. CSV-vereisten

De workflow verwacht een CSV met ten minste de kolommen `Date` en `IV30`.
Andere kolommen worden genegeerd, maar blijven bruikbaar voor handmatige
controles. Houd rekening met het volgende:

- `Date` wordt automatisch geconverteerd naar `YYYY-MM-DD` en accepteert de
  meest voorkomende notaties (`YYYY-MM-DD`, `DD-MM-YYYY`, `MM/DD/YYYY`, enz.).
- `IV30` moet een numerieke waarde bevatten (in procenten). De CLI zet deze om
  naar een fractie (`0.455` → `45.5%`). Lege waarden of ontbrekende kolommen
  worden overgeslagen en tellen mee in het foutenrapport.
- Dubbele datums in de CSV worden gemeld maar slechts één keer ingelezen. Voor
  extra validatie worden fouten/warnmeldingen gelogd, zodat de operator de CSV
  kan corrigeren voordat er weggeschreven wordt.

Zie §2.2 en §3.2 van de analyse voor achtergrond over het schema en de
kolomkeuze.

## 2. CLI-workflow stap voor stap

1. Start het Control Panel (`python -m tomic.cli.controlpanel`) en kies in het
   menu **Data & Marktdata → IV backfill**.
2. Vul het symbool in (hoofdletters aanbevolen) en het pad naar de CSV.
3. De CLI parseert de CSV en toont een voorbeeldtabel met de eerste 12
   wijzigingen, gevolgd door een samenvatting met onder andere:
   - aantal nieuwe dagen en updates (diff > 3%)
   - duplicaten, lege/ongeldige rijen en CSV-hiaten
   - ontbrekende HV- en spot-data per datum
4. Warnings worden direct weergegeven, bijvoorbeeld wanneer HV of spot-data
   ontbreken. Dit zijn informatieve meldingen; de flow start géén HV-backfill.
5. Bevestig met `Y` om te schrijven. Bij `N` voert de CLI een dry-run uit en
   schrijft niets naar disk.
6. Bij een bevestigde write:
   - Bestaat het `iv_daily_summary/<SYMBOL>.json` al, dan wordt eerst een
     `.bak` back-up gemaakt.
   - De dataset wordt samengevoegd en gesorteerd op datum.
   - Het totale recordaantal wordt getoond zodat downstream-controles de
     omvang kunnen valideren.

## 3. Beperkingen en bekende waarschuwingen

- **Geen automatische HV-backfill.** De workflow controleert wel of HV-data
  ontbreekt, maar schrijft zelf geen HV-waarden weg. Gebruik de bestaande HV-
  scripts (bijv. `compute_volstats`) om hiaten te vullen voordat je de IV
  definitief publiceert.
- **Spotdata waarschuwingen.** Wanneer slotkoersen ontbreken, geeft de CLI een
  duidelijke melding. Spotdata wordt niet automatisch ingeladen; draai indien
  nodig `fetch_prices(_polygon)` voor dezelfde periode.
- **CSV-validatie blijft beperkt.** Alleen basiscontroles op kolomnamen,
  datumnotaties en numerieke waarden worden uitgevoerd. Onverwachte extra
  kolommen worden genegeerd.
- **Tabulate-afhankelijkheid optioneel.** Als `tabulate` niet beschikbaar is,
  valt de CLI terug op een eenvoudige tabelweergave. Dit beïnvloedt de
  functionaliteit niet.

## 4. Testdekking en regressies

Om regressies te voorkomen is er unit- én integratiedekking:

- `tests/cli/test_iv_backfill_flow.py::test_read_iv_csv_*` controleert het
  parser- en validatiegedrag (datumnormalisatie, duplicaten, foutmeldingen).
- `tests/cli/test_iv_backfill_flow.py::test_run_iv_backfill_flow_previews_and_writes`
  voert de volledige interactieve flow uit in een temp-directory, inclusief
  preview, waarschuwingen en bulk write + back-up.
- Draai daarnaast rooktests voor downstream consumers wanneer je IV-data
  bijwerkt:
  - `pytest tests/analysis/test_market_overview.py`
  - `pytest tests/services/test_strategy_pipeline.py`

Deze checks sluiten aan bij §6 uit de analyse en helpen om effecten op market
overview, strategie-pipeline en rules vroegtijdig te signaleren.

## 5. Veelvoorkomende problemen

| Foutmelding | Oorzaak | Oplossing |
|-------------|---------|-----------|
| `Ontbrekende kolommen in CSV` | CSV mist `Date` of `IV30` | Controleer exportprofiel en voeg de kolommen toe |
| `CSV inlezen mislukt` | Onleesbaar bestand (encoding, quotes) | Open de CSV en exporteer opnieuw met UTF-8 en standaard delimiter |
| `⚠️ HV ontbreekt voor X dagen` | HV JSON mist dezelfde datums | Draai het HV-backfill script voordat je de IV publiceert |
| `⚠️ Spotdata ontbreekt` | Spotprijzen ontbreken | Voer `fetch_prices` of `fetch_prices_polygon` uit |

Met deze richtlijnen blijft de IV-backfill workflow consistent met de
architectuurkeuzes en downstream-processen die in de analyse zijn beschreven.
