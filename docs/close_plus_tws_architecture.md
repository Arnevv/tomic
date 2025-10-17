# Architectuurwijzigingen voor close + TWS-bid/ask stroom

Deze notitie schetst welke onderdelen van de Tomic-pijplijn we moeten aanpassen om de nieuw gekozen koers – **close-data als baseline met opportunistische TWS-bid/ask refreshes** – te ondersteunen. Het doel is dat strategie-generatie niet langer geblokkeerd raakt door ontbrekende Polygon-bid/ask quotes, terwijl we wel duidelijke waarborgen inbouwen zodra live TWS-data arriveert.

## 1. Baseline spot- en close-data
- **`tomic/helpers/price_utils._load_latest_close`** moet de close van gisteren blijven teruggeven maar uitbreiden met metadata (timestamp, bron). Hierdoor kan downstream-logica weten hoe “oud” de close is en eventueel een verouderingspenalty toepassen.【F:tomic/helpers/price_utils.py†L1-L33】
- **`tomic/polygon_prices.request_bars`** moet de meta-informatie over de laatst verwerkte close opslaan zodat we detecteren wanneer de close al in lijn ligt met de meest recente handelsdag. Op dit moment voeren we al een sanity check uit op de laatste handelsdag; we breiden dit uit door de baseline-close expliciet als “primary mid seed” te markeren voor de option-chain builders.【F:tomic/polygon_prices.py†L1-L114】

## 2. Option-chain normalisatie
- **`tomic/strategies/utils.prepare_option_chain`** vult nu missende mids met parity; voeg hier een stap aan toe die, na het aanroepen van `fill_missing_mid_with_parity`, per leg vastlegt of de mid uit close/parity/model komt. We bewaren deze info via `mid_source` zodat de pijplijn weet dat de quote nog niet uit TWS komt.【F:tomic/strategies/utils.py†L186-L231】
- Voeg een configurable “close confidence” drempel toe: als de parity- of model-mids meer dan X% afwijken van de close-baseline, markeren we de leg met `spread_flag="needs_refresh"` zodat de pipeline later prioriteit geeft aan TWS refreshes.

## 3. Strategie-scoringspijplijn
- **`tomic/services/strategy_pipeline.py`** verwerkt nu al `fallback_summary`. Breid dit uit met een scoring-penalty voor legs waarvan `mid_source in {"close", "parity_close", "model"}` zodat we transparant zijn over het gebruik van geschatte quotes maar de strategie niet volledig blokkeren.【F:tomic/services/strategy_pipeline.py†L600-L666】
- Introduceer een nieuwe stap vóór publicatie van voorstellen: controleer of alle legs met een geschatte mid binnen de vooraf ingestelde risicobuffer vallen ten opzichte van de close. Als de buffer overschreden wordt, label de strategie als `requires_live_quote` i.p.v. ze te verwijderen. Zo blijft ze zichtbaar maar vraagt expliciet om een TWS-refresh.

## 4. TWS-refresh & herwaardering
- **`tomic/services/ib_marketdata.IBMarketDataService._apply_snapshot`** moet na een geslaagde bid/ask refresh de statusvelden opschonen (`mid_source="true"`, `mid_reason="IB streaming bid/ask"`). Dit doen we nu al, maar breiden uit met logging van het verschil tussen de oude close-baseline en de nieuwe mid zodat we kunnen evalueren of de risicobuffer correct gekozen is.【F:tomic/services/ib_marketdata.py†L563-L608】
- Voeg aan `fetch_quote_snapshot` een stap toe die – wanneer er grote afwijkingen zijn – automatische herberekening van EV/edge en eventuele herprioritering binnen de watchlist triggert. Denk aan het herberekenen van score en margin zodra `mid_source` naar “true” verschuift.

## 5. Governance & monitoring
- Leg in de monitoringlaag vast hoeveel strategieën live staan met uitsluitend close/parity mids. Gebruik de bestaande logging in `IBMarketDataService` en `StrategyPipeline` om dashboards te voeden die aangeven waar live quotes nog ontbreken.
- Automatiseer alerts wanneer een voorstel na X minuten nog steeds geen TWS-update heeft ontvangen terwijl `spread_flag="needs_refresh"` staat. Zo houden we de risico’s beheersbaar zonder de pipeline te verlammen.

Met deze aanpassingen kunnen we de nieuwe visie – werken vanuit een stabiele close-baseline en incrementieel upgraden zodra TWS-data binnenkomt – afdwingen in zowel data-inname, chain-preparatie als strategie-evaluatie.
