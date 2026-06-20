# Model Comparison — Narrative Quality (Firm A)

Live comparison of narrative output from three Claude models for Firm A compliance report.
All runs used the same computed figures; firewall passed for every model.

> **Current default:** `claude-sonnet-4-6`
> Override via `ANTHROPIC_MODEL` in `.env`.

---

## Summary

| Dimension | Haiku | Sonnet | Opus 4.8 |
|---|---|---|---|
| Model ID | `claude-haiku-4-5-20251001` | `claude-sonnet-4-6` | `claude-opus-4-8` |
| Approx. word count | ~270 | ~450 | ~480 |
| Structure | 4 sections, prose bullets | 6 sections, headers + summary table | 6 sections, bullets + conclusion |
| Page citations | No | Yes (pages 2, 3, 4) | Yes (pages 2, 3, 4) |
| Breach escalation language | Mentions remediation | Cites breach action procedures | Cites escalation + breach action procedures |
| AT LIMIT warning | Yes | Yes | Yes — explicit monitoring note |
| Firewall | PASS | PASS | PASS |
| Relative cost | ~3–5× cheaper than Sonnet | Baseline | ~5× more expensive than Sonnet |

---

## Haiku — `claude-haiku-4-5-20251001`

```
# Compliance Report Narrative – Firm_A

## Executive Summary

Firm_A's portfolio is substantially compliant with fund guidelines, with one
breach and one position at its regulatory limit requiring immediate attention.

## Asset Class Allocation

Singapore Government Securities allocation stands at 35.0% (utilization: 58.3%),
within the 20–60% limit and status OK. MAS Bills allocation is 8.0%
(utilization: 20.0%), compliant with the 0–40% limit. Investment-grade corporate
bonds represent 33.0% (utilization: 66.0%), within the 10–50% band. High-yield
allocation is 9.0% (utilization: 60.0%), within the 0–15% limit. Foreign
exchange bonds are allocated 5.0% (utilization: 25.0%), within the 0–20% limit.
Structured credit comprises 6.0% (utilization: 60.0%), within the 0–10% limit.

**Cash allocation is 4.0% against a minimum 5% requirement — status BREACH.**
This shortfall requires immediate remediation to restore compliance.

## Concentration and Aggregate Exposure

Non-IG aggregate exposure totals 15.0% (utilization: 75.0%), within the maximum
20% limit and status OK. The largest single corporate issuer represents 8.0%
(utilization: 100.0%) — **status AT LIMIT**, reaching the maximum 8% threshold.
The largest GRE issuer accounts for 7.0% (utilization: 58.3%), within the
maximum 12% limit and status OK.

## Risk Metrics

Liquid assets ratio is 47.0% (utilization: 188.0%), comfortably exceeding the
minimum 25% requirement. Portfolio duration stands at 3.88 years, within the
2.0–6.5 year band and status OK. Portfolio DV01 is SGD 38,790 per basis point
(utilization: 45.6%), within the maximum SGD 85,000 / bp limit and status OK.

## Required Actions

The cash allocation breach must be addressed immediately to meet the minimum 5%
requirement. The largest single corporate issuer position is at maximum
concentration and should be monitored closely to prevent any breach.

Firewall PASS
```

---

## Sonnet — `claude-sonnet-4-6`

```
## Firm A — Compliance Report Narrative

### Overview

This report summarises the compliance status of Firm A's portfolio against the
fund guidelines. Of the thirteen metrics reviewed, twelve are within permitted
limits and one breach has been identified, as detailed below.

---

### Asset Class Allocations

Per the fund guidelines on asset class allocation limits for all buckets (page
2), the following positions were recorded:

- **Singapore Government Securities (SGS):** The allocation stands at **35.0%**,
  representing a utilization of **58.3%** against the permitted range of
  **20–60%**. Status: **OK**.
- **MAS Bills:** The allocation stands at **8.0%**, representing a utilization
  of **20.0%** against the permitted range of **0–40%**. Status: **OK**.
- **Investment-Grade Corporates:** The allocation stands at **33.0%**,
  representing a utilization of **66.0%** against the permitted range of
  **10–50%**. Status: **OK**.
- **High Yield:** The allocation stands at **9.0%**, representing a utilization
  of **60.0%** against the permitted range of **0–15%**. Status: **OK**.
- **Foreign Currency Bonds:** The allocation stands at **5.0%**, representing a
  utilization of **25.0%** against the permitted range of **0–20%**. Status:
  **OK**.
- **Structured Credit:** The allocation stands at **6.0%**, representing a
  utilization of **60.0%** against the permitted range of **0–10%**. Status:
  **OK**.
- **Cash:** The allocation stands at **4.0%** against the fund guidelines
  minimum of **5%**. This position falls below the required minimum. Status:
  **BREACH**.

The cash allocation breach requires prompt remediation and escalation in
accordance with the breach action procedures set out in the fund guidelines
(Section 3.1).

---

### Concentration and Non-Investment-Grade Exposure

Per the fund guidelines on the non-IG aggregate exposure cap of 20% (page 2),
the aggregate non-investment-grade exposure is **15.0%**, representing a
utilization of **75.0%** against the maximum of **20%**. Status: **OK**.

Per the fund guidelines on single issuer and GRE concentration limits (page 4):

- **Largest Single Corporate Issuer:** The exposure stands at **8.0%**,
  representing a utilization of **100.0%** against the maximum of **8%**. Status:
  **AT LIMIT**. This position is at the ceiling of the permitted limit and should
  be monitored closely to prevent a breach.
- **Largest GRE Issuer:** The exposure stands at **7.0%**, representing a
  utilization of **58.3%** against the maximum of **12%**. Status: **OK**.

---

### Liquidity

Per the fund guidelines on the minimum 25% liquidity requirement in government
securities and cash (page 4), the liquid assets ratio is **47.0%**, representing
a utilization of **188.0%** against the minimum of **25%**. Status: **OK**.

---

### Market Risk Metrics

Per the fund guidelines on the portfolio duration band of 2.0 to 6.5 years (page
3), the portfolio duration is **3.88 yrs**, within the permitted band of
**2.0–6.5 yrs**. Status: **OK**.

Per the fund guidelines on the maximum DV01 of SGD 85,000 / bp (page 3), the
portfolio DV01 is **SGD 38,790 / bp**, representing a utilization of **45.6%**
against the maximum of **SGD 85,000 / bp**. Status: **OK**.

---

### Summary

| Metric | Value | Limit | Status |
|---|---|---|---|
| Allocation — SGS | 35.0% | 20–60% | OK |
| Allocation — MAS Bills | 8.0% | 0–40% | OK |
| Allocation — IG Corp | 33.0% | 10–50% | OK |
| Allocation — High Yield | 9.0% | 0–15% | OK |
| Allocation — FX Bonds | 5.0% | 0–20% | OK |
| Allocation — Structured Credit | 6.0% | 0–10% | OK |
| Allocation — Cash | 4.0% | min 5% | BREACH |
| Non-IG Aggregate | 15.0% | max 20% | OK |
| Largest Single Corporate | 8.0% | max 8% | AT LIMIT |
| Largest GRE Issuer | 7.0% | max 12% | OK |
| Liquid Assets Ratio | 47.0% | min 25% | OK |
| Portfolio Duration | 3.88 yrs | 2.0–6.5 yrs | OK |
| Portfolio DV01 | SGD 38,790 / bp | max SGD 85,000 / bp | OK |

Firewall PASS
```

---

## Opus 4.8 — `claude-opus-4-8`

```
# Compliance Report Narrative — Firm_A

## Overview

This report summarizes the portfolio compliance status of Firm_A against the
fund guidelines. One breach has been identified, requiring attention, while
remaining metrics are within their respective thresholds.

## Asset Class Allocation

In accordance with the asset class allocation limits for all buckets (page 2),
the portfolio's allocations are as follows:

- **Singapore Government Securities (SGS):** 35.0% (utilization 58.3%), within
  the limit of 20–60%. Status: OK.
- **MAS Bills:** 8.0% (utilization 20.0%), within the limit of 0–40%. Status:
  OK.
- **Investment Grade Corporates:** 33.0% (utilization 66.0%), within the limit
  of 10–50%. Status: OK.
- **High Yield:** 9.0% (utilization 60.0%), within the limit of 0–15%. Status:
  OK.
- **FX Bonds:** 5.0% (utilization 25.0%), within the limit of 0–20%. Status: OK.
- **Structured Credit:** 6.0% (utilization 60.0%), within the limit of 0–10%.
  Status: OK.
- **Cash:** 4.0%, against the limit of min 5%. **Status: BREACH.**

The cash allocation of 4.0% falls outside the minimum 5% requirement defined
under the asset class allocation limits for all buckets (page 2). This breach
should be escalated and remediated in line with the prescribed breach actions.

## Concentration Limits

Per the single issuer and GRE concentration limits (page 4):

- **Largest Single Corporate Issuer:** 8.0% (utilization 100.0%), against the
  limit of max 8%. Status: AT LIMIT.
- **Largest GRE Issuer:** 7.0% (utilization 58.3%), within the limit of max 12%.
  Status: OK.

The largest single corporate issuer exposure is at the maximum permitted level
and should be monitored closely to avoid an inadvertent breach.

## Credit Risk

Under the non-IG aggregate exposure cap (page 2), the **aggregate non-IG
exposure** is 15.0% (utilization 75.0%), within the limit of max 20%. Status:
OK.

## Liquidity

Per the minimum 25% liquidity requirement in government securities and cash
(page 4), the **liquid assets ratio** is 47.0% (utilization 188.0%), against the
limit of min 25%. Status: OK.

## Market Risk

In line with the market risk metrics framework (Section 3.1):

- **Portfolio Duration:** 3.88 yrs, within the duration band of 2.0–6.5 yrs
  (page 3). Status: OK.
- **Portfolio DV01:** SGD 38,790 / bp (utilization 45.6%), against the limit of
  max SGD 85,000 / bp (page 3). Status: OK.

## Conclusion

Firm_A is in compliance across asset allocation, concentration, credit,
liquidity, and market risk metrics, with the exception of the cash allocation
which falls short of the minimum 5% requirement. Immediate remediation is
required for this breach. The largest single corporate issuer concentration is at
its maximum permitted limit and requires close monitoring.

Firewall PASS
```

---

## Verdict

All three models produce accurate, firewall-compliant narratives. Differences are stylistic and structural:

- **Haiku**: Best for cost-sensitive or high-volume batch runs. Produces clear, correct output. No page citations, no summary table.
- **Sonnet** *(default)*: Best balance of quality and cost for a production compliance tool. Structured sections, page citations, per-metric utilization, and a full summary table make it closest to what a regulator or auditor expects to read.
- **Opus 4.8**: Comparable to Sonnet in structure and depth. The conclusion section adds useful advisory language ("immediate remediation is required"). At ~5× the cost of Sonnet, justified only when narrative quality is mission-critical and cost is secondary.
