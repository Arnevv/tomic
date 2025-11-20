# Changelog

## Unreleased

### Removed
- TWS option-chain fetch workflows, including bulk export en single-option stappen. Gebruik de Polygon-paden voor keteninformatie.
- Configuratievlag `data_sources.tws_option_chain_enabled` en bijbehorende code - TWS option chains zijn volledig verwijderd, alleen Polygon wordt gebruikt.
- Menu-optie "998 → (niet beschikbaar) IB snapshot-refresh" uit het hoofdmenu (Volatility Snapshot Aanbevelingen).

### Added
- Regressietest die faalt wanneer verboden TWS-symbolen opnieuw worden geïntroduceerd.
- CLI-test die bevestigt dat het menu een nette melding toont wanneer gebruikers de TWS-optie kiezen.

### Changed
- Menu-optie "998 → IB snapshot-refresh" in Candidates menu gebruikt nu altijd Polygon voor option chains (geen TWS conditie meer).
