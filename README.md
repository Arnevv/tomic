# TOMIC – Tactical Option Management & Insight Console

Een Python-project voor het beheren, analyseren en afsluiten van optieposities via de IBKR TWS API. Inclusief datalogging, trade journal, Greeks-analyse en CSV-export.

---

## ✅ Features

* Ophalen van live portfolio en openstaande orders
* Exporteren van option chains met Greeks naar CSV-bestanden
* Snapshotten van marktdata: IV, HV, VIX, skew, ATR
* Handmatig en scriptmatig beheren van trades in `journal.json`
* Greeks-analyse per positie (Delta, Gamma, Theta, Vega)
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

---

## 🕹️ Gebruik

Start het hoofdscript met het controlpanel:

```bash
python controlpanel.py
```

Of gebruik individuele modules:

* `getaccountinfo.py`: Live portfolio-overzicht ophalen
  (slaat posities op in `positions.json`)
* `getonemarket.py`: Optieketen en marktdata voor een symbool
* `getallmarkets.py`: Exporteert data voor meerdere symbolen
* `journal_updater.py`: Nieuwe trade aanmaken en loggen
* `close_trade.py`: Trade afsluiten met evaluatie
* `strategy_dashboard.py`: Groepeert legs per strategie en toont alerts
* `portfolio_scenario.py`: Simuleert PnL/Greeks na een zelf gekozen spot- en IV-shift

---

## 📂 Bestanden en mappen

* `exports/` – Dagelijkse CSV-export van optiegegevens en marktdata
* `Backups/` – Back-ups van eerdere scriptversies
* `journal.json` – Trade journal met open en gesloten posities

---

### `csv_quality_check.py`

Validatie van geëxporteerde option-chain CSV's. Het script toont het aantal
regels, compleetheid en extra controles:

- Delta buiten het bereik [-1, 1]
- Ongeldige Strike/Bid/Ask waarden
- Aantal gedupliceerde regels

Gebruik:

```bash
python csv_quality_check.py <pad/naar/csv> [SYMBOL]
```

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
Kwaliteit: 95.0%
```

---

## 📈 Voorbeeld: spotprijs & Greeks snapshot

```
[Step 2] ✅ SPY spotprijs ontvangen: 594.20
[Step 3] ✅ Drie reguliere expiries: 20250621, 20250719, 20250816
[Step 5] ✅ Market data requests initiated
```

---

## 📄 Disclaimer

Dit project is uitsluitend bedoeld voor educatieve en persoonlijke trading-doeleinden. Geen financieel advies.

---

## Licentie

[MIT License](LICENSE)
