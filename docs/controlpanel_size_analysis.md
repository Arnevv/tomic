# Analyse van `tomic/cli/controlpanel.py`

## Methode
- Het bestand bestaat uit 3.427 regels broncode (inclusief lege regels en commentaar).【815d08†L1-L2】
- Via een AST-analyse zijn alle top-level functies en klassen onderzocht. Binnen iedere functie is een onderscheid gemaakt tussen regels die UI-interacties bevatten (`Menu`, `prompt`, `print`, `input`, `tabulate`) en alle overige regels. Lege regels en commentaar zijn buiten beschouwing gelaten.
- De tellingen zijn heuristisch: UI-gerelateerde regels binnen dezelfde functies kunnen nog steeds logica bevatten, maar geven een goede ordegrootte om te bepalen waar de complexiteit zit.【7142a4†L1-L17】

## Hoofdbevindingen
- Van de 2.818 niet-lege regels binnen functies is ~90% (2.531 regels) pure logica, tegenover slechts 287 regels die direct UI/navigatie-code bevatten.【7142a4†L1-L17】
- De drie dataklassen (`ReasonAggregator`, `ExpiryBreakdown`, `EvaluationSummary`) voegen nog eens 118 regels logica toe.【b18fa4†L1-L16】
- De grootste functie, `run_portfolio_menu`, beslaat bijna 1.000 regels inclusief hulpfuncties en bevat uitgebreide data-verwerking (portfolio-ophalen, tabulaire overzichten, scans, statistiek) naast menu-afhandeling.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L2208-L3132】
- Ook andere menu-functies zoals `run_dataexporter` en `run_settings_menu` bevatten honderden regels logica voor bestandsverwerking, validatie en externe service-aanroepen.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1850-L2166】【F:tomic/cli/controlpanel.py†L3135-L3399】

## Detailoverzicht van de grootste blokken
Onderstaande tabel toont de belangrijkste functies met ≥40 niet-lege regels en de verdeling tussen UI- en logica-regels.

| Functie | Regels totaal | UI | Logica | Belangrijke verantwoordelijkheden |
| --- | ---:| ---:| ---:| --- |
| `run_portfolio_menu` | 851 | 86 | 765 | Portfolio ophalen, dashboard draaien, fact-sheets opbouwen, marktdata scannen, aanbevelingen filteren, voorstellen selecteren.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L2208-L3132】 |
| `run_dataexporter` | 279 | 55 | 224 | CSV-import, kwaliteitschecks, exportpaden beheren, IV-backfill triggeren.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1850-L2166】 |
| `run_settings_menu` | 236 | 39 | 197 | Configuratiebestanden lezen/schrijven, default-symbolen bijwerken, hulproutines voor strike-config en criteria laden.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L3135-L3399】 |
| `_show_proposal_details` | 175 | 25 | 150 | Analyse van strategiemetrics, tabellen genereren, earnings-informatie tonen.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1009-L1196】 |
| `_refresh_reject_entries` | 142 | 14 | 128 | Pipeline opnieuw draaien, afwijzingen filteren, redenaggregatie bijwerken.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L833-L987】 |
| `_build_rejection_table` | 135 | 0 | 135 | Sorteren, scoren en formatteren van afwijzingen tot tabellen.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L515-L661】 |
| `_export_proposal_json` | 118 | 1 | 117 | Portfolio-context laden, JSON-serialisatie, bestandsbeheer voor exports.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1425-L1545】 |
| `_show_rejection_detail` | 105 | 16 | 89 | Detailweergave met reden, legs, metrics, earning-context.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L664-L775】 |
| `_print_reason_summary` | 93 | 22 | 71 | Categoriseren en presenteren van redenstatistieken.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1572-L1674】 |
| `_export_proposal_csv` | 83 | 1 | 82 | CSV-export met uitgebreide kolomopbouw, prijsdata laden, berekeningen uitvoeren.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1285-L1367】 |
| `_submit_ib_order` | 52 | 5 | 47 | Ordervoorbereiding, IB-submissie, foutafhandeling.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1199-L1254】 |
| `refresh_spot_price` | 48 | 0 | 48 | Spotprijs herladen uit ketens, prijsmeta bijwerken, logging.【193508†L2-L12】【F:tomic/cli/controlpanel.py†L1732-L1785】 |

## Mogelijke modularisatiekansen
- **Reden- en afwijzingslogica**: `ReasonAggregator`, `_build_rejection_table`, `_print_reason_summary` en gerelateerde helpers vormen een coherent geheel dat naar een `rejections`- of `reporting`-module kan worden verplaatst.【F:tomic/cli/controlpanel.py†L172-L661】【F:tomic/cli/controlpanel.py†L1572-L1674】
- **Exportfunctionaliteit**: `_export_proposal_csv`, `_export_proposal_json` en `_proposal_journal_text` delen veel IO-/serialisatielogica en zouden in een dedicated exportmodule passen.【F:tomic/cli/controlpanel.py†L1285-L1569】
- **Portfolio- en marktdata**: Binnen `run_portfolio_menu` zitten zelfstandige routines voor factsheet-berekening, markt-snapshots en scanner-configuratie die in services/modules ondergebracht kunnen worden.【F:tomic/cli/controlpanel.py†L2208-L2488】
- **Pipeline-refresh en filtering**: `_refresh_reject_entries`, `_show_rejection_detail` en `_proposal_from_rejection` gebruiken `StrategyPipeline` en doen uitgebreide datamanipulatie. Deze stappen kunnen naar een service-laag verhuizen zodat het menu alleen resultaten toont.【F:tomic/cli/controlpanel.py†L664-L987】【F:tomic/cli/controlpanel.py†L778-L817】

## Conclusie
De controlpanel-CLI bevat relatief weinig code die strikt nodig is voor interactie en navigatie; het merendeel van het bestand implementeert domeinlogica (berekeningen, formattering, bestandsbeheer) die beter thuishoort in herbruikbare modules. Een opsplitsing van de hierboven genoemde blokken zou het bestand aanzienlijk verkleinen en de onderhoudbaarheid vergroten, terwijl de UI-laag zich kan focussen op menus en gebruikersinteractie.
