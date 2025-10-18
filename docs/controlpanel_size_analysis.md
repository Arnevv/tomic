# Analyse van het herstructureerde controlpanel

## Nieuwe module-indeling
- `tomic/cli/controlpanel/__init__.py`: bouwt de root-`Menu` via declaratieve `MenuSection`-configuratie, beheert de gedeelde `ControlPanelContext`, exporteert wrappers voor bestaande CLI-handlers en houdt `SESSION_STATE` synchroon met de actieve `ControlPanelSession`.
- `tomic/cli/controlpanel/__main__.py`: dunne runner die `python -m tomic.cli.controlpanel` (of het `tomic`-CLI-subcommando) naar `main()` dispatcht zodat de historisch gebruikte startwijze behouden blijft.
- `tomic/cli/controlpanel/portfolio.py`: bevat de volledige set handlers voor portfolio-, export- en riskomenu's, inclusief `_process_chain_with_context`, `_show_proposal_details` en alle IO/logica rond strategie-evaluaties.【F:tomic/cli/controlpanel/portfolio.py†L379-L700】
- `tomic/cli/controlpanel/menu_config.py`: definieert de declaratieve `MenuItem`- en `MenuSection`-dataclasses plus een helper om submenus op basis van secties te bouwen.【F:tomic/cli/controlpanel/menu_config.py†L1-L44】

De vroegere monolithische `controlpanel.py` is vervangen door een package waarbij de entrypointmodule enkel menu-opbouw en contextbeheer uitvoert. Domeinlogica leeft nu in submodules die los van de UI kunnen worden getest of hergebruikt.

## Belangrijkste componenten
- `SessionState`: dictionary-achtige proxy die mutaties in tests (zoals `SESSION_STATE.update(...)`) direct terugschrijft naar de actieve `ControlPanelSession`. Bij `clear()` wordt een nieuwe sessie en servicecontainer aangemaakt, waarna de proxy opnieuw gevuld wordt met defaultwaarden.【F:tomic/cli/controlpanel/__init__.py†L33-L86】
- `ROOT_SECTIONS`: lijst van `MenuSection`-objecten die de root-menustructuur beschrijven (Analyse, Data, Trades, Risico, Configuratie). Iedere sectie verwijst naar een handlerfunctie in `portfolio.py` en opent een submenu via `build_menu`.【F:tomic/cli/controlpanel/__init__.py†L94-L169】
- `_process_chain(path)`: wrapper die `_process_chain_with_context` uit `portfolio.py` aanroept, `SHOW_REASONS` bijwerkt en vervolgens `SESSION_STATE` synchroniseert. Hiermee blijven bestaande tests die `_process_chain` patchen compatibel.【F:tomic/cli/controlpanel/__init__.py†L172-L181】

## Impact op onderhoudbaarheid
- `main()` doet niets anders dan argumenten parsen, `SHOW_REASONS` zetten en `run_controlpanel()` starten.【F:tomic/cli/controlpanel/__init__.py†L184-L197】 Hiermee verdwijnt alle businesslogica uit het entrypoint.
- Menu-opties verwijzen nu naar top-level functies (via `functools.partial` waar nodig), waardoor nested functies verdwijnen en handlers herbruikbaar zijn in tests.【F:tomic/cli/controlpanel/portfolio.py†L407-L699】
- Door de declaratieve secties is het eenvoudig om nieuwe top-level categorieën toe te voegen zonder UI-code in meerdere plaatsen aan te passen.

## Volgende stappen
- Extra opsplitsing van `portfolio.py` (bijv. `rejections.py`, `orders.py`) kan de module verder verkleinen en testbaarheid verhogen.
- Overweeg om reporting/exportfunctionaliteit naar dedicated services te verplaatsen zoals eerder aanbevolen in de oorspronkelijke analyse.
