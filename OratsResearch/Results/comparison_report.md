# ORATS vs Polygon Validation Report

**Periode:** October 2025
**Symbolen:** AAPL, MSFT, NVDA, SPY, TSLA
**Totaal vergelijkingen:** 15

## 🏆 Overall Winner: **ORATS ✓**

| Metric | ORATS | Polygon | Status |
|--------|-------|---------|--------|
| Completeness | 100.0% | 100% | ✓ PASS |
| ATM IV Accuracy | Δ0.14% | - | ✓ PASS |
| Skew Consistency | 15/15 ✓ | - | ✓ PASS |

### ✅ Acceptatie: **GO** voor ORATS integratie

**Reden:**
- Voldoet aan alle harde criteria (≥95% completeness, ≤0.5% IV diff)
- Skew logica consistent in minimaal 90% van gevallen
- Data kwaliteit gelijkwaardig of beter dan Polygon

## Detailed Breakdown

### AAPL (3 dagen)

- Gemiddeld 50 strikes per dag
- Completeness: 100.0%
- ATM IV Δ: 0.06% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 23.7% | 23.8% | 0.09% | ✓ |
| 2025-11-20 | 50 | 100.0% | 26.0% | 26.1% | 0.07% | ✓ |
| 2025-11-21 | 50 | 100.0% | 25.6% | 25.6% | 0.00% | ✓ |

### MSFT (3 dagen)

- Gemiddeld 50 strikes per dag
- Completeness: 100.0%
- ATM IV Δ: 0.24% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 18.1% | 18.3% | 0.19% | ✓ |
| 2025-11-20 | 50 | 100.0% | 29.2% | 29.6% | 0.35% | ✓ |
| 2025-11-21 | 50 | 100.0% | 25.6% | 25.8% | 0.17% | ✓ |

### NVDA (3 dagen)

- Gemiddeld 50 strikes per dag
- Completeness: 100.0%
- ATM IV Δ: 0.10% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 26.5% | 26.6% | 0.17% | ✓ |
| 2025-11-20 | 50 | 100.0% | 51.8% | 51.8% | 0.01% | ✓ |
| 2025-11-21 | 50 | 100.0% | 48.3% | 48.4% | 0.12% | ✓ |

### SPY (3 dagen)

- Gemiddeld 50 strikes per dag
- Completeness: 100.0%
- ATM IV Δ: 0.08% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 20.1% | 20.1% | 0.00% | ✓ |
| 2025-11-20 | 50 | 100.0% | 22.0% | 22.1% | 0.09% | ✓ |
| 2025-11-21 | 50 | 100.0% | 20.2% | 20.3% | 0.16% | ✓ |

### TSLA (3 dagen)

- Gemiddeld 50 strikes per dag
- Completeness: 100.0%
- ATM IV Δ: 0.21% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 46.7% | 46.9% | 0.17% | ✓ |
| 2025-11-20 | 50 | 100.0% | 56.0% | 56.3% | 0.27% | ✓ |
| 2025-11-21 | 50 | 100.0% | 52.3% | 52.5% | 0.18% | ✓ |

## 🚩 Red Flags

**NONE** - All validation criteria passed ✓

## 📈 Recommendation

**Proceed met ORATS backfill vanaf 2022.**

ORATS data voldoet aan alle kwaliteitscriteria en is geschikt als primaire IV-bron.
Deprecate MC-data zodra ORATS 2-jarige historie complete is.
