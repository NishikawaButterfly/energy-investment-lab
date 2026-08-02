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

## Debt

A loan is drawn in full at year 0 and repaid as an annuity: the same
payment every year, split into interest on the opening balance and
principal. For principal `P`, rate `r`, and tenor `n` years:

```
annuity factor = r / (1 - (1 + r)^-n)
payment        = P * annuity factor
```

The final payment retires the remaining balance exactly, absorbing
sub-cent floating-point residue, so the closing balance ends at zero.

### Worked example, continued

The same asset borrows 600,000 EUR at 6% over 5 years.

```
1.06^5         = 1.338226
annuity factor = 0.06 / (1 - 1 / 1.338226) = 0.237396
payment        = 600,000 * 0.237396 = 142,437.84 EUR per year
```

The amortization table, rounded to cents:

| Year | Opening | Interest | Principal | Payment | Closing |
|-----:|--------:|---------:|----------:|--------:|--------:|
| 1 | 600,000.00 | 36,000.00 | 106,437.84 | 142,437.84 | 493,562.16 |
| 2 | 493,562.16 | 29,613.73 | 112,824.11 | 142,437.84 | 380,738.05 |
| 3 | 380,738.05 | 22,844.28 | 119,593.56 | 142,437.84 | 261,144.49 |
| 4 | 261,144.49 | 15,668.67 | 126,769.17 | 142,437.84 | 134,375.32 |
| 5 | 134,375.32 | 8,062.52 | 134,375.32 | 142,437.84 | 0.00 |

Spot check: year-1 interest is 600,000 × 0.06 = 36,000, so the year-1
principal is 142,437.84 − 36,000 = 106,437.84.

### DSCR

CFADS (cash flow available for debt service) is the project operating
cash flow: revenue minus opex, before any debt service. The DSCR of a
year is CFADS divided by the debt service:

```
DSCR(1) = 120,000.00 / 142,437.84 = 0.8425
DSCR(5) = 129,891.86 / 142,437.84 = 0.9119
```

The minimum is year 1 at 0.8425. Every covered year sits below 1.0, so
this financing does not service itself from operating cash flow — the
model flags exactly that, which is the point of computing it.

### Equity cash flows

Equity puts in capex minus principal at year 0 and receives each year's
project cash flow minus the debt service:

```
year 0:      -1,000,000 + 600,000            = -400,000.00
year 1:      120,000.00 - 142,437.84         = -22,437.84
years 2..5:  still negative, DSCR below one
year 6:      132,489.70 (debt fully repaid)
```

Discounting the equity stream at the same 8% gives an equity NPV of
-97,973.55 EUR. The stream has exactly one sign change (negative through
year 5, positive from year 6), so a unique equity IRR exists:

```
equity IRR = 4.7013%
```

Borrowing at 6% against a project earning 5.13% drags the equity return
below the project return — leverage amplifies in both directions.

Without a loan, the financed evaluation reproduces the unlevered project
numbers exactly, with empty debt tables.
