# ORATS vs Polygon Validation Report

**Periode:** October 2025
**Symbolen:** AAPL, MSFT, NVDA, SPY, TSLA
**Totaal vergelijkingen:** 15

## 🏆 Overall Winner: **NEEDS REVIEW ⚠**

| Metric | ORATS | Polygon | Status |
|--------|-------|---------|--------|
| Completeness | 100.0% | 100% | ✓ PASS |
| ATM IV Accuracy | Δ1.96% | - | ✗ FAIL |
| Skew Consistency | 15/15 ✓ | - | ✓ PASS |

### ⚠ Acceptatie: **REVIEW VEREIST**

**Issues:**
- ✗ ATM IV verschil 1.96% > 0.5% vereist

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
- ATM IV Δ: 9.20% gemiddeld

| Date | Strikes | Completeness | ATM IV (ORATS) | ATM IV (Polygon) | Δ | Skew OK |
|------|---------|--------------|----------------|------------------|---|----------|
| 2025-11-19 | 50 | 100.0% | 26.5% | 53.6% | 27.17% | ✓ |
| 2025-11-20 | 50 | 100.0% | 51.8% | 52.2% | 0.32% | ✓ |
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

- **ATM IV deviation:** 1.96% average difference (target: ≤0.5%)

## 📈 Recommendation

**Onderzoek data kwaliteit issues voordat je verdergaat.**

Los de geïdentificeerde red flags op voordat ORATS in productie gaat.
