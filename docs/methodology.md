# Methodology

This document explains how the engine turns an asset description into a
cash-flow table and the core metrics, using one worked example with round
numbers. Every figure below was computed by hand with the formulas shown,
and the test suite asserts these exact digits. If the code and this
document ever disagree, one of them is wrong.

## The cash-flow table

An asset spends its capex at year 0. Each operating year `t` from 1 to the
project life earns every revenue stream escalated from its year-1 amount,
and pays the fixed opex escalated the same way:

```
revenue(t) = year_one_amount * (1 + escalation)^(t - 1)
opex(t)    = fixed_opex      * (1 + opex_escalation)^(t - 1)
net(t)     = revenue(t) - opex(t)
```

The discount factor for year `t` is `1 / (1 + rate)^t`, with year 0 never
discounted.

## Worked example

- Capex: 1,000,000 EUR at year 0
- One revenue stream: 150,000 EUR in year 1, escalating 2% per year
- Fixed opex: 30,000 EUR in year 1, escalating 2% per year
- Project life: 10 years
- Discount rate: 8%

Because revenue and opex share the same escalation, the net flow is simply
120,000 × 1.02^(t−1). The full table, rounded to cents:

| Year | Revenue | Opex | Net flow | Factor | Discounted | Cumulative | Cum. discounted |
|-----:|--------:|-----:|---------:|-------:|-----------:|-----------:|----------------:|
| 0 | 0.00 | 0.00 | -1,000,000.00 | 1.000000 | -1,000,000.00 | -1,000,000.00 | -1,000,000.00 |
| 1 | 150,000.00 | 30,000.00 | 120,000.00 | 0.925926 | 111,111.11 | -880,000.00 | -888,888.89 |
| 2 | 153,000.00 | 30,600.00 | 122,400.00 | 0.857339 | 104,938.27 | -757,600.00 | -783,950.62 |
| 3 | 156,060.00 | 31,212.00 | 124,848.00 | 0.793832 | 99,108.37 | -632,752.00 | -684,842.25 |
| 4 | 159,181.20 | 31,836.24 | 127,344.96 | 0.735030 | 93,602.35 | -505,407.04 | -591,239.90 |
| 5 | 162,364.82 | 32,472.96 | 129,891.86 | 0.680583 | 88,402.22 | -375,515.18 | -502,837.69 |
| 6 | 165,612.12 | 33,122.42 | 132,489.70 | 0.630170 | 83,490.98 | -243,025.48 | -419,346.70 |
| 7 | 168,924.36 | 33,784.87 | 135,139.49 | 0.583490 | 78,852.59 | -107,885.99 | -340,494.11 |
| 8 | 172,302.85 | 34,460.57 | 137,842.28 | 0.540269 | 74,471.89 | 29,956.29 | -266,022.21 |
| 9 | 175,748.91 | 35,149.78 | 140,599.13 | 0.500249 | 70,334.57 | 170,555.41 | -195,687.65 |
| 10 | 179,263.89 | 35,852.78 | 143,411.11 | 0.463193 | 66,427.09 | 313,966.52 | -129,260.55 |

Spot checks. Year 4 revenue is 150,000 × 1.02³ = 150,000 × 1.061208 =
159,181.20. The year-4 factor is 1/1.08⁴ = 0.735030, so the discounted
flow is 127,344.96 × 0.735030 = 93,602.35.

### NPV

The NPV is the last cumulative discounted value:

```
NPV = -1,000,000 + 111,111.11 + ... + 66,427.09 = -129,260.55 EUR
```

The project does not clear an 8% hurdle.

### IRR

The IRR is the rate that makes the NPV zero. The stream has exactly one
sign change (negative at year 0, positive afterwards), so a unique
conventional IRR exists, and bisection finds

```
IRR = 5.1310%
```

Check: discounting the table at 5.1310% instead of 8% gives an NPV within
a few euros of zero. Since 5.13% < 8%, the IRR agrees with the negative NPV.
Streams with zero or several sign changes have no unique IRR, and the
engine reports none rather than guessing.

### Payback

Simple payback interpolates inside the year where the cumulative flow
crosses zero. The cumulative flow is -107,885.99 after year 7 and turns
positive during year 8, which brings in 137,842.28:

```
simple payback = 7 + 107,885.99 / 137,842.28 = 7.7827 years
```

Discounted payback applies the same rule to the cumulative discounted
column. That column is still -129,260.55 at year 10, so the discounted
payback never happens and the engine reports none.
