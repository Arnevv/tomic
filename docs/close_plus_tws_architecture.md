# EOD-architectuur voor close-gedreven scoring

Deze notitie beschrijft hoe de huidige Tomic-stack volledig op sluitingsdata
(End-Of-Day) draait. Live TWS-snapshots en intraday-refreshes zijn verwijderd:
voorstellen blijven gebaseerd op de meest recente close totdat een nieuwe batch
wordt binnengehaald. De beslisflow blijft: *MidResolver labelt, Scoring beslist,
CLI visualiseert*.

## 1. Baseline spot- en close-data
- **Close ophalen en dateren.** `tomic/helpers/price_utils._load_latest_close`
  levert `(prijs, datum, bron)` zodat downstream logica altijd weet dat de data
  uit een EOD-run komt.【F:tomic/helpers/price_utils.py†L1-L41】
- **Metadata rond close-fetches.** `tomic/helpers/price_meta.load_price_meta`
  bewaakt wanneer er voor het laatst bars zijn opgehaald en markeert de huidige
  close als primaire bron.【F:tomic/helpers/price_meta.py†L1-L39】
- **Spot-resolutie voor scans.** `tomic/services/chain_processing.resolve_spot_price`
  probeert eerst de meest recente close en logt expliciet dat de bron `close`
  is. Er wordt niet meer doorgeschakeld naar TWS.【F:tomic/services/chain_processing.py†L201-L230】
- **Gebruik binnen de marktscan.** `tomic/services/market_scan_service.MarketScanService.run_market_scan`
  hergebruikt dezelfde close/spot-waardes voor alle strategieën en markeert
  elke `ScanRow` als preview zolang alleen sluitingsdata beschikbaar is.【F:tomic/services/market_scan_service.py†L70-L177】

## 2. Option-chain normalisatie & mid-metadata
- **Ketenvoorbereiding.** `tomic/services/chain_processing.load_and_prepare_chain`
  normaliseert CSV-ketens en behoudt de `close`-kolom zodat `MidResolver`
  deze als mid kan gebruiken.【F:tomic/services/chain_processing.py†L61-L199】
- **MidResolver als centrale waarheid.** `tomic/mid_resolver.MidResolver`
  labelt elke leg met `mid`, `mid_source`, `mid_reason` en zet `mid_source`
  standaard op `close` als er geen andere bron is.【F:tomic/mid_resolver.py†L1-L312】
- **Reason-mapper als helper.** `tomic/strategy/reasons.reason_from_mid_source`
  vertaalt de bron naar een UI-label zodat "Preview (close)" overal
  consistent getoond wordt.【F:tomic/strategy/reasons.py†L121-L147】

## 3. Strategie-scoringspijplijn
- **Close-first scoring.** `tomic/services/strategy_pipeline.StrategyPipeline.build_proposals`
  werkt uitsluitend met de verrijkte keten vanuit `MidResolver`; intraday
  refreshes bestaan niet meer.【F:tomic/services/strategy_pipeline.py†L1-L214】
- **Samenvattingen van bronnen.** Tijdens `_convert_proposal` wordt
  `fallback_summary` opgebouwd met uitsluitend close-bronnen zodat het panel
  ziet dat een setup een nieuwe close-run nodig heeft.【F:tomic/services/strategy_pipeline.py†L595-L659】
- **Config-gedreven validatie.** `tomic/analysis/scoring.validate_entry_quality`
  controleert of close-data voldoet aan de acceptance-regels en vermeldt in de
  log wanneer een leg te oud is.【F:tomic/analysis/scoring.py†L560-L712】
- **Controlpanel-weergave.** `tomic/services/portfolio_service.PortfolioService._mid_sources`
  vat de `mid_source`-waarden samen en presenteert enkel `preview` of `rejected`
  badges; `tradable` bestaat niet meer zonder live quotes.【F:tomic/services/portfolio_service.py†L141-L235】

## 4. Governance & monitoring
- **Rejection dashboards.** `StrategyPipeline` bewaart `last_rejections` en
  `last_evaluated` zodat dashboards kunnen tonen hoeveel voorstellen op
  close-data bleven hangen.【F:tomic/services/strategy_pipeline.py†L215-L365】
- **Mid-bron rapportage.** De `Candidate` uit `PortfolioService.rank_candidates`
  bevat `mid_sources` en `score` zodat rapportages duidelijk maken dat de bron
  `close` is.【F:tomic/services/portfolio_service.py†L141-L235】
- **Logging voor audits.** `tomic/analysis/scoring.validate_entry_quality` logt
  expliciet wanneer mids uit close komen en welke criteria ze misten. Exits
  gebruiken `validate_exit_tradability` zodat ontbrekende model/delta-waarden
  geen blokkade meer vormen.【F:tomic/analysis/scoring.py†L560-L712】【F:tomic/analysis/scoring.py†L714-L788】

## 5. Testfocus
- **Unit-tests.** Bevestigen dat close als standaardbron fungeert en dat
  voorstellen met alleen EOD-data geen extra refresh proberen te starten.
- **Integratietests.** Scenario's waarin voorstellen uitsluitend op close-data
  draaien blijven groen, zelfs zonder IB-sessies.
- **Regression.** "Top reason" rapporteert altijd dat een voorstel in preview
  staat zolang `mid_source="close"` is.

## 6. Actiepunten
1. **MidResolver:** houdt alleen close- en model-bronnen over; verwijder oude
   TWS-refresh hooks.
2. **Scoringlaag:** vertrouwt volledig op close-data en toont strengere waarschuwingen
   wanneer datasets ouder zijn dan één handelsdag.
3. **CLI/controlpanel:** benadrukt dat exports preview-kwaliteit hebben tot een
   nieuwe EOD-run heeft gedraaid.
