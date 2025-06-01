# TOMIC – Tactical Option Management & Insight Console

Een Python-project voor het beheren, analyseren en afsluiten van optieposities via de IBKR TWS API. Inclusief datalogging, trade journal, Greeks-analyse en CSV-export.

---

## ✅ Features

* Ophalen van live portfolio en openstaande orders  
* Exporteren van option chains met Greeks naar CSV-bestanden  
* Snapshotten van marktdata: IV, HV, VIX, skew, ATR  
* Handmatig en scriptmatig beheren van trades in het journalbestand (`JOURNAL_FILE`)
* Greeks-analyse per positie (Delta, Gamma, Vega, Theta)
* Interactief Control Panel met toegang tot alle scripts  
* Dashboard dat legs groepeert tot strategieën met alerts  

---

## ⚙️ Installatie

1. Clone deze repository:

```bash
git clone https://github.com/Arnevv/tomic.git
cd tomic
```

2. Activeer een virtuele omgeving:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

3. Installeer dependencies:

```bash
pip install -r requirements.txt
```

4. Zorg dat IB Gateway of TWS actief is op poort 7497.

### Logging

Alle scripts gebruiken **loguru** voor consistente logging. Als `loguru` niet
geïnstalleerd is, valt het systeem automatisch terug op het standaard
`logging`-pakket. Uitgebreide `ibapi`-logs worden standaard onderdrukt.
Stel `TOMIC_LOG_LEVEL=DEBUG` of `TOMIC_DEBUG=1` in om deze en andere
debugberichten te tonen.

### Omgevingsvariabelen instellen

Linux en macOS gebruiken de `VAR=waarde` syntaxis voor eenmalige
omgevingsvariabelen:

```bash
TOMIC_DEBUG=1 python tomic/api/getaccountinfo.py
```

In **PowerShell** werkt dat anders. Gebruik daar:

```powershell
$env:TOMIC_DEBUG = 1
python tomic/api/getaccountinfo.py
```

En in de klassieke **cmd.exe**-prompt:

```cmd
set TOMIC_DEBUG=1 && python tomic/api/getaccountinfo.py
```

Zo voorkom je de melding `TOMIC_DEBUG=0 : The term 'TOMIC_DEBUG=0' is not recognized...`.

---

## 🕹️ Gebruik

Start het hoofdscript met het controlpanel:

```bash
python -m tomic.cli.controlpanel
```

Of gebruik individuele modules:

* `tomic.api.getaccountinfo`: Live portfolio-overzicht ophalen
* `tomic.api.getonemarket`: Optieketen en marktdata voor een symbool
* `tomic.api.getallmarkets`: Exporteert data voor meerdere symbolen
* `tomic.api.getallmarkets_async`: Prototype dat meerdere markten parallel ophaalt
* `tomic.journal.journal_updater`: Nieuwe trade aanmaken en loggen
* `tomic.cli.close_trade`: Trade afsluiten met evaluatie
* `tomic.cli.strategy_dashboard`: Groepeert legs per strategie en toont alerts
* `tomic.cli.portfolio_scenario`: Simuleert PnL/Greeks na een zelf gekozen spot- en IV-shift
* `tomic.cli.csv_quality_check`: Controleert CSV-exports op fouten (ook via het Control Panel)

### Asynchrone prototype

`getallmarkets_async.py` toont hoe de bestaande marktdatascripts parallel kunnen
lopen met `asyncio.to_thread`. De IBKR-API zelf is niet echt asynchroon, maar op
deze manier kun je wel meerdere symbolen gelijktijdig verwerken.

## 📦 Pakketstructuur

Alle logica staat nu in de map `tomic`. De belangrijkste subpakketten zijn:

- `tomic.api` – interactie met de IB API (o.a. `getaccountinfo`, `getonemarket`, `getallmarkets`, `margin_calc`).
- `tomic.analysis` – analysetools zoals `performance_analyzer` en `get_iv_rank`.
- `tomic.journal` – beheer van het trade journal.

Alle utilities kunnen direct worden gestart met `python -m <module>`. De losse wrappers in de hoofdmap zijn verwijderd voor meer duidelijkheid.

### Configuratie

Het bestand `tomic/config.py` zoekt automatisch naar `config.yaml`, `config.yml` of `.env` in de projectmap. Via de omgevingsvariabele `TOMIC_CONFIG` kun je een ander pad opgeven. YAML-bestanden vereisen de optionele dependency **PyYAML**.

Belangrijke sleutels die je hier kunt aanpassen:

* `EXPORT_DIR` – map voor CSV-exports (standaard `exports/`)
* `POSITIONS_FILE` – JSON-bestand met open posities
* `ACCOUNT_INFO_FILE` – JSON-bestand met accountgegevens
* `PORTFOLIO_META_FILE` – JSON-bestand met timestamp van laatste portfolio update
* `JOURNAL_FILE` – trade journal
* `VOLATILITY_DATA_FILE` – snapshots van volatiliteitsdata
* `IB_HOST` – hostnaam voor de IB Gateway/TWS (standaard `127.0.0.1`)
* `IB_PORT` – poortnummer voor de IB Gateway/TWS (standaard `7497`)

---

## 📂 Bestanden en mappen

* `exports/` – Dagelijkse CSV-export van optiegegevens en marktdata  
* `Backups/` – Back-ups van eerdere scriptversies  
* `journal.json` – Standaardnaam voor het trade journal (instelbaar via `JOURNAL_FILE`)

---

## 🔄 Automatische regressietest

Deze functionaliteit is verwijderd. Gebruik de unit tests om de belangrijkste logica te verifiëren.

---

## 🧪 Unit tests

De map `tests/` bevat eenvoudige unittests voor kernfuncties. Na het installeren van de
afhankelijkheden kunnen de tests worden uitgevoerd met:

```bash
pytest
```

---

### csv_quality_check

Validatie van geëxporteerde option-chain CSV's. Het script toont het aantal regels, compleetheid en extra controles:

- Delta buiten het bereik [-1, 1]
- Ongeldige Strike/Bid/Ask waarden
- Aantal gedupliceerde regels
- Bid of Ask met waarde -1

Gebruik:

```bash
python -m tomic.cli.csv_quality_check [optioneel pad/naar/bestand.csv]
```

Laat je het pad weg, dan vraagt het script om het bestand en optioneel het symbool. Het script is ook te starten via het Control Panel (Dataexporter-menu).

Voorbeeldoutput:

```
Markt: SPY
Expiries: 20250620 / 20250718
Aantal regels: 100
Aantal complete regels: 95
Aantal semi-complete regels: 5
Delta buiten [-1,1]: 0
Ongeldige Strike/Bid/Ask: 1
Duplicaten: 0
Bid/Ask == -1: 0
Kwaliteit: 95.0%
```

---

## 📈 Voorbeeld: spotprijs & Greeks snapshot

```
[Step 2] ✅ SPY spotprijs ontvangen: 594.20
[Step 3] ✅ Drie reguliere expiries + vier weeklies: 20250621, 20250719, 20250816, ...
[Step 5] ✅ Market data requests initiated
```

---

## 📄 Disclaimer

Dit project is uitsluitend bedoeld voor educatieve en persoonlijke trading-doeleinden. Geen financieel advies.

---

## Licentie

[MIT License](LICENSE)
