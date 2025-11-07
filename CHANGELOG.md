# Changelog

## Unreleased

### Removed
- TWS option-chain fetch workflows, including bulk export en single-option stappen. Gebruik de Polygon-paden voor keteninformatie.

### Added
- Configuratievlag `data_sources.tws_option_chain_enabled` om duidelijk te maken dat TWS-optionchains zijn uitgeschakeld.
- Regressietest die faalt wanneer verboden TWS-symbolen opnieuw worden geïntroduceerd.
- CLI-test die bevestigt dat het menu een nette melding toont wanneer gebruikers de TWS-optie kiezen.
