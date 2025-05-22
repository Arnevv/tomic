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
python controlpanel_20250517.py
```

Of gebruik individuele modules:

* `getaccountinfo_20250517.py`: Live portfolio-overzicht ophalen
* `getfulloptionchain_20250517.py`: Optieketen + Greeks exporteren
* `journal_updater_20250517.py`: Nieuwe trade aanmaken en loggen
* `close_trade_20250518.py`: Trade afsluiten met evaluatie

---

## 📂 Bestanden en mappen

* `exports/` – Dagelijkse CSV-export van optiegegevens en marktdata
* `Backups/` – Back-ups van eerdere scriptversies
* `journal.json` – Trade journal met open en gesloten posities

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
