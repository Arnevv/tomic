## 🎯 Doel van deze repository

Deze repository bevat de AI-agents die onderdeel zijn van het TOMIC-systeem. Elke agent heeft een heldere, afgebakende verantwoordelijkheid binnen de trading pipeline — van dataverzameling tot journaling en signaalgeneratie.

## 🛠️ Architectuurprincipes

### 1. Modulariteit & Separation of Concerns

- **Ieder script of module moet één taak hebben**. Vermijd "God scripts" die data ophalen, verwerken én loggen.
- Herbruikbare onderdelen zoals `greeks_calculator`, `volatility_analyzer` en `trade_selector` leven in `/core/` of `/utils/`.
- **Agents orchestreren**, maar doen zelf zo min mogelijk.

### 2. Configuratie boven hardcodering

- Alle parameters zoals symbolen, filters, thresholds en outputinstellingen staan in:
  - `config/base.yaml` voor defaults
  - `.env` voor secrets
- **Gebruik `dynaconf` of `pydantic`** voor robuuste, getypeerde config parsing.

### 3. Logging & Error Handling

- Gebruik centrale logging via `loguru` of `structlog`.
- Iedere module logt minimaal:
  - start & succes van operatie
  - uitzonderingen of edge cases
  - relevante metrics zoals aantal gefilterde trades
- Bij fouten:
  - Geef gebruiker een duidelijke melding
  - Log stacktrace + fallback-beslissing

### 4. Testbaarheid

- Modules zijn testbaar zonder externe services (mock IB API bijv.).
- Structuur:
  ```
  /tests/
    test_greeks.py
    test_filtering.py
    ...
  ```
- Elke core module heeft een `pytest` test-suite met edge cases.

### 5. Schaalbaarheid & Performance

- Gebruik `asyncio` waar zinvol voor API-calls (bijv. IBKR, nieuwsfeeds).
- Zorg dat agents batchgewijs of per symbool werken (géén one-shot over alles).
- Optimaliseer filtering op pandas-niveau, niet via loops.

### 6. Versiebeheer van outputs

- Alle outputbestanden (bijv. signalen, journals) bevatten timestamp en config-hash in de naam:
  ```
  /output/2025-05-31_SIGNALS_QQQ_ironcondor_d1ab2c.csv
  ```
- Elke run logt:
  - gebruikte config
  - timestamp
  - versie van relevante inputs (bijv. IV-data snapshot ID)

### 7. Heldere dataflow & documentatie

- 📈 Genereer en onderhoud een **pipeline-diagram** (`docs/dataflow.png`) met:
  - Input → Modules → Output
  - Dependencies tussen agents
- Gebruik docstrings + Markdown (`README.md` per module) voor developer onboarding.

## 🧪 Agents in deze repo

| Agent | Doel | Output |
|--|--|--|
| `fetch_marketdata.py` | Ophalen spot, IV, HV, skew e.d. | `/data/raw/symbolname_TIMESTAMP.json` |
| `filter_candidates.py` | Filter op IV Rank, skew, DTE, delta, volume | CSV met qualifyende combinaties |
| `generate_signals.py` | Pas TOMIC-richtlijnen toe en kies top 5 combinaties | `/signals/DATE_signals.json` |
| `journal_writer.py` | Genereert journaling-entry per trade | `/journal/DATE_tradeID.json` |

## 📚 Bronnen

- 📘 *The Option Trader's Hedge Fund* (Chen & Sebastian) – leidend voor strategieconstructie.
- 📑 Interne modules: `greeks.py`, `volatility.py`, `entry_rules.py`
- 🧾 IBKR API (official): <https://ibkrcampus.com/campus/ibkr-api-page/twsapi-doc>

## 🧹 Code Conventies

- Schrijf in **Python 3.10+**, met `pyproject.toml` als package-manager.
- Gebruik `black`, `ruff` en `mypy` voor format, linting en types.
- Typ alle functies expliciet, incl. return types.

## ✅ CI/CD (toekomst)

- Via `GitHub Actions` willen we dagelijks:
  - marktdata ophalen (`fetch_marketdata`)
  - filter draaien
  - signalen loggen
- `CI` test alle PR’s automatisch op regressie en broken dependencies.