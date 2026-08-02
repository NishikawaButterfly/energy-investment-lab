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

## Modified IRR (MIRR)

The IRR silently assumes every interim flow is reinvested at the IRR
itself. The MIRR replaces that assumption with two explicit rates: the
negative flows are discounted to year 0 at a finance rate (what funding
the outlays costs), and the positive flows are compounded to the final
year `N` at a reinvestment rate (what interim cash actually earns). With
each side collapsed into a single number:

```
MIRR = (FV_positive / |PV_negative|)^(1/N) - 1
```

A stream with no negative flow has no investment side, and one with no
positive flow has no return side, so in both cases no MIRR exists and
the function reports none. When both rates equal the IRR, the MIRR is
the IRR again — the tests assert this property.

### Worked example, continued

The sample project with a 6% finance rate and a 4% reinvestment rate.
The only negative flow is the capex at year 0, which needs no
discounting, so |PV_negative| = 1,000,000.00 exactly. Each positive net
flow compounds to year 10 at 4%:

| Year | Net flow | 1.04^(10-t) | Future value |
|-----:|---------:|------------:|-------------:|
| 1 | 120,000.00 | 1.423312 | 170,797.42 |
| 2 | 122,400.00 | 1.368569 | 167,512.85 |
| 3 | 124,848.00 | 1.315932 | 164,291.45 |
| 4 | 127,344.96 | 1.265319 | 161,132.00 |
| 5 | 129,891.86 | 1.216653 | 158,033.31 |
| 6 | 132,489.70 | 1.169859 | 154,994.21 |
| 7 | 135,139.49 | 1.124864 | 152,013.55 |
| 8 | 137,842.28 | 1.081600 | 149,090.21 |
| 9 | 140,599.13 | 1.040000 | 146,223.09 |
| 10 | 143,411.11 | 1.000000 | 143,411.11 |

Summing the unrounded column gives FV_positive = 1,567,499.19 (the
cents-rounded display values sum one cent higher), so

```
MIRR = (1,567,499.19 / 1,000,000.00)^(1/10) - 1
     = 1.567499^0.1 - 1 = 4.5974%
```

Spot check: year-8 net flow 137,842.28 × 1.04² = 137,842.28 × 1.0816 =
149,090.21. The MIRR lands between the 4% reinvestment rate and the
5.1310% IRR, as it must: the interim flows now earn 4% instead of the
IRR, which drags the compound return below 5.1310% without erasing the
project's own margin over 4%. The same function applies unchanged to
equity flows, where the finance rate also discounts the negative
operating years, not just year 0.

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

## Levelized cost (LCOE and LCOS)

The levelized cost is the constant price per MWh that, earned on every
MWh over the project life, would exactly repay the discounted costs:

```
LCOE = (capex + PV of opex) / (PV of energy)
```

The energy comes from a profile that degrades from its year-1 amount,
mirroring how costs escalate from theirs:

```
energy(t) = year_one_energy * (1 - degradation)^(t - 1)
```

Both the cost flows and the energy are discounted at the asset's
discount rate. Discounting energy — a physical quantity — is a
convention, not physics, and it is worth being honest about why it is
used: a constant price `p` earns `p × energy(t)` each year, whose
present value is `p × PV(energy)`; setting that equal to the PV of the
costs and solving for `p` gives exactly the formula above. Dividing by
discounted MWh is what makes the levelized cost a break-even price
rather than an average cost. This is the standard formulation used by
IEA, NREL, and Lazard, and this model follows it.

For a generator the profile is produced energy and the result is the
LCOE. For a storage asset the profile is discharged energy and the same
number is called the LCOS. One function computes both — only the
profile changes its meaning. Revenues never enter the calculation.

### Worked example, continued

The sample asset generates 2,000 MWh in year 1, degrading 0.5% per
year. At the same 8% discount rate:

| Year | Opex | Energy (MWh) | Factor | Disc. opex | Disc. energy |
|-----:|-----:|-------------:|-------:|-----------:|-------------:|
| 1 | 30,000.00 | 2,000.00 | 0.925926 | 27,777.78 | 1,851.85 |
| 2 | 30,600.00 | 1,990.00 | 0.857339 | 26,234.57 | 1,706.10 |
| 3 | 31,212.00 | 1,980.05 | 0.793832 | 24,777.09 | 1,571.83 |
| 4 | 31,836.24 | 1,970.15 | 0.735030 | 23,400.59 | 1,448.12 |
| 5 | 32,472.96 | 1,960.30 | 0.680583 | 22,100.55 | 1,334.15 |
| 6 | 33,122.42 | 1,950.50 | 0.630170 | 20,872.75 | 1,229.14 |
| 7 | 33,784.87 | 1,940.75 | 0.583490 | 19,713.15 | 1,132.41 |
| 8 | 34,460.57 | 1,931.04 | 0.540269 | 18,617.97 | 1,043.28 |
| 9 | 35,149.78 | 1,921.39 | 0.500249 | 17,583.64 | 961.17 |
| 10 | 35,852.78 | 1,911.78 | 0.463193 | 16,606.77 | 885.52 |

Spot check: year-4 energy is 2,000 × 0.995³ = 2,000 × 0.985075 =
1,970.15 MWh, and discounted it is 1,970.15 × 0.735030 = 1,448.12.
Summing the unrounded columns (the cents-rounded display values can sum
a cent off):

```
PV of costs  = 1,000,000 + 217,684.86 = 1,217,684.86 EUR
PV of energy = 13,163.58 MWh
LCOE         = 1,217,684.86 / 13,163.58 = 92.50 EUR/MWh
```

Without degradation the discounted energy would be 13,420.16 MWh and
the LCOE 90.74 EUR/MWh: degradation only ever shrinks the denominator,
so it can only raise the levelized cost.

## Taxes, depreciation, and grants

The fiscal layer sits on top of the financed evaluation. Capex net of an
optional capital grant is depreciated straight-line, and the taxable
result of an operating year is the operating result minus depreciation
minus loan interest when a loan is present — interest is deductible,
principal repayment is not:

```
depreciable base = capex - grant
depreciation(t)  = base / depreciation_years   for t = 1 .. depreciation_years
taxable(t)       = net(t) - depreciation(t) - interest(t)
```

The grant arrives as cash at year 0 and reduces the depreciable base; it
is not taxed as income. A negative taxable result is never refunded:
it becomes a tax loss carried forward without time limit — the standard
unlimited-carryforward treatment — and offsets the next positive taxable
results before any tax is charged. The tax of a year is the rate times
the taxable base left after loss relief, and the same tax reduces both
the project and the equity cash flow of that year: one entity, one tax
bill.

Inflation deliberately has no knob of its own. The asset already
escalates every revenue stream and the fixed opex independently, so
nominal (inflated) cash flows are expressed there; a global inflation
rate would only duplicate those escalations.

### Worked example, continued

The same asset and the same 600,000 EUR loan, now with a 25% tax rate,
straight-line depreciation over 10 years, and a 100,000 EUR grant.

The depreciable base is 1,000,000 − 100,000 = 900,000 EUR, so
depreciation is 90,000 per year in every operating year. The tax table,
rounded to cents:

| Year | Net flow | Depreciation | Interest | Taxable | Loss used | Taxed base | Tax | Carryforward |
|-----:|---------:|-------------:|---------:|--------:|----------:|-----------:|----:|-------------:|
| 1 | 120,000.00 | 90,000.00 | 36,000.00 | -6,000.00 | 0.00 | 0.00 | 0.00 | 6,000.00 |
| 2 | 122,400.00 | 90,000.00 | 29,613.73 | 2,786.27 | 2,786.27 | 0.00 | 0.00 | 3,213.73 |
| 3 | 124,848.00 | 90,000.00 | 22,844.28 | 12,003.72 | 3,213.73 | 8,789.99 | 2,197.50 | 0.00 |
| 4 | 127,344.96 | 90,000.00 | 15,668.67 | 21,676.29 | 0.00 | 21,676.29 | 5,419.07 | 0.00 |
| 5 | 129,891.86 | 90,000.00 | 8,062.52 | 31,829.34 | 0.00 | 31,829.34 | 7,957.33 | 0.00 |
| 6 | 132,489.70 | 90,000.00 | 0.00 | 42,489.70 | 0.00 | 42,489.70 | 10,622.42 | 0.00 |
| 7 | 135,139.49 | 90,000.00 | 0.00 | 45,139.49 | 0.00 | 45,139.49 | 11,284.87 | 0.00 |
| 8 | 137,842.28 | 90,000.00 | 0.00 | 47,842.28 | 0.00 | 47,842.28 | 11,960.57 | 0.00 |
| 9 | 140,599.13 | 90,000.00 | 0.00 | 50,599.13 | 0.00 | 50,599.13 | 12,649.78 | 0.00 |
| 10 | 143,411.11 | 90,000.00 | 0.00 | 53,411.11 | 0.00 | 53,411.11 | 13,352.78 | 0.00 |

Spot check. Year 3's tax is (12,003.72 − 3,213.73) × 0.25 = 8,789.99 ×
0.25 = 2,197.50. Years 5 and 6 land on a half cent when recomputed from
the rounded columns; at full precision their taxes are 7,957.334985 and
10,622.424096, which the table rounds to cents.

Years 1 and 2 pay no tax. Year 1 runs a taxable loss of 120,000 − 90,000
− 36,000 = −6,000, which carries forward. Year 2 earns 122,400 − 90,000
− 29,613.73 = 2,786.27, absorbed entirely by that loss, leaving 3,213.73
carried forward. Taxes first become payable in year 3: 124,848 − 90,000
− 22,844.28 = 12,003.72, and the remaining 3,213.73 of losses leaves a
taxed base of 8,789.99, so the tax is 8,789.99 × 0.25 = 2,197.50. From
year 6 the loan is repaid and depreciation is the only deduction. The
taxes over the whole life add up to 75,444.33 EUR.

### After-tax NPV

Each after-tax cash flow is the pre-tax flow, plus the grant at year 0,
minus the tax of the year. The after-tax NPV is therefore the pre-tax
NPV plus the grant minus the present value of the tax column, which
discounted at 8% is 43,396.68 EUR:

```
after-tax NPV        = -129,260.55 + 100,000 - 43,396.68 = -72,657.23 EUR
after-tax equity NPV =  -97,973.55 + 100,000 - 43,396.68 = -41,370.23 EUR
```

Year 0 improves by the grant (the project now spends 900,000, the equity
300,000), so the after-tax IRR of 6.1952% and equity IRR of 6.3145% both
sit above their pre-tax counterparts, and the simple after-tax payback
shortens to 7.3604 years — though the project still misses the 8%
hurdle. The discounted payback still never happens.

With a zero tax rate and no grant the fiscal evaluation reproduces every
pre-tax number exactly.

## One-at-a-time sensitivities

A sensitivity spec is an ordered list of variants, each changing exactly
one parameter — as a multiplier on the base value or an absolute
replacement — while everything else stays at base. The parameters are
`capex_eur`, `discount_rate`, and `opex_eur`, plus every revenue
stream's year-1 amount addressed by the stream's name, plus
`loan_principal_eur` and `loan_rate` when the evaluation has a loan and
`tax_rate` when it has fiscal rules. Base and variants together are
capped at 32 runs, and unknown parameters are rejected with the exact
supported list.

Every run goes through the same evaluation entry points a direct call
would use, so a sensitivity row can never disagree with a direct
evaluation — the tests assert the base row equals one exactly. Each
flat row carries the NPV, IRR, MIRR, both paybacks, and, when levered,
the minimum DSCR; the base row is flagged. The MIRR uses the evaluated
asset's discount rate as both the finance and the reinvestment rate —
the documented defaults — so a `discount_rate` variant moves them too.

### Worked example, continued

Five variants on the sample asset: capex ±20%, the `energy sales`
stream ±20%, and the discount rate set to 6%.

| Variant | NPV | IRR | MIRR | Simple payback |
|:--------|----:|----:|-----:|---------------:|
| base | -129,260.55 | 5.1310% | 6.5154% | 7.7827 |
| capex_eur\*0.8 | 70,739.45 | 9.8601% | 8.9190% | 6.3184 |
| capex_eur\*1.2 | -329,260.55 | 1.6344% | 4.5910% | 9.2053 |
| energy sales\*0.8 | -346,945.42 | -0.2575% | 3.4948% | — |
| energy sales\*1.2 | 88,424.31 | 9.8601% | 8.9190% | 6.3184 |
| discount_rate=0.06 | -42,040.35 | 5.1310% | 5.5457% | 7.7827 |

Every NPV above is recomputable from the earlier tables. Capex enters
at year 0 undiscounted, so ±20% of it moves the NPV by exactly
±200,000: -129,260.55 + 200,000 = 70,739.45. For the revenue variants,
the discounted net flows of the main table sum to 870,739.45 (the NPV
plus the capex), and since revenue is 150/120 of the net flow, its
present value is 1.25 × 870,739.45 = 1,088,424.31. Twenty percent of
that is 217,684.86 — exactly the PV of the opex column from the
levelized-cost section, because opex is itself 20% of revenue — so

```
energy sales +20%: NPV = -129,260.55 + 217,684.86 =   88,424.31
energy sales -20%: NPV = -129,260.55 - 217,684.86 = -346,945.41
```

(the -20% case lands one cent off the full-precision -346,945.42, the
usual cents-rounding residue). Three sanity checks the table makes
visible: the discount-rate variant leaves the IRR untouched, because
the IRR never depended on the discount rate, while its MIRR drops to
5.5457% as the default rates follow the asset; `capex_eur*0.8` and
`energy sales*1.2` share the same IRR, MIRR, and paybacks because
their cash-flow streams are proportional (one is 1.25 times the
other) even though their NPVs differ; and `energy sales*0.8` never
pays back — its IRR turns negative and both paybacks vanish.

## Monte Carlo simulation

Uncertainty enters as dimensionless multipliers on three inputs: the
capex, any revenue stream's year-1 amount (picked by name), and the
fixed opex. Each uncertain input gets one distribution from a closed
set — `Normal(mean, stddev)` truncated below at a floor, `Uniform(low,
high)`, or `Triangular(low, mode, high)` — and every run multiplies the
deterministic value by a fresh draw, rebuilds the asset through the same
validation as a hand-written one, and evaluates it through the existing
engine, debt, and fiscal layers. Nothing is recomputed differently.

**The seed is mandatory.** An unseeded simulation cannot be re-run to
the same numbers, so none of its figures can be checked — and a figure
that cannot be checked has no place in this model. The same seed always
reproduces the same result, number for number; the seed and run count
are embedded in the result so any report can cite them.

**Truncation.** The normal distribution is truncated by redrawing: a
draw at or below the floor (default 0) is thrown away and drawn again.
This yields a true truncated normal — no probability mass piles up on
the floor, as clamping would cause. The floor must sit below the mean,
which keeps over half the distribution acceptable and guarantees the
redraw loop terminates quickly. A floor of 0 simply forbids negative
multipliers, which would turn a cost into a revenue.

**Percentiles.** The 5/25/50/75/95 percentiles use linear interpolation
between closest ranks: the sorted values take ranks 0 through n − 1,
the target rank for level `p` is `p / 100 × (n − 1)`, and a fractional
rank interpolates linearly between its two neighbours. For the sorted
values 10, 20, 30, 40, 50 the 5th percentile has rank 0.2, giving
10 + 0.2 × (20 − 10) = 12, and the 25th has rank 1.0, giving exactly
20 — the tests assert these digits. IRR percentiles cover only the runs
where a unique IRR exists; runs without one are counted and reported
alongside, never silently dropped into the statistics.

**Sanity bound.** With `Uniform(0.9, 1.1)` on revenue as the only
uncertainty, every simulated NPV must lie between the NPVs of the
deterministic −10% and +10% revenue variants, because NPV is monotone
in a revenue multiplier. The test suite asserts that envelope on 500
runs rather than trusting any hand-computed percentile. A degenerate
`Uniform(1, 1)` on every input reproduces the deterministic base
exactly for every run, with zero standard deviation.
