# The scenario file and the CLI

The kernel evaluates assets handed to it as Python objects. The CLI wraps
that in one JSON document — the scenario — so a whole investment case can
be described, versioned, and rerun from a single file. `investlab run`
evaluates a scenario and writes two artifacts; `investlab validate`
checks a file without evaluating anything.

## The scenario document

A scenario is a single JSON object. The `asset` block is required; every
other block is optional, and the run evaluates exactly what is present.
The shipped example, [sample-data/scenario.json](../sample-data/scenario.json),
describes a fictional 20 MW solar asset with a 12,000,000 EUR capex, a
7,000,000 EUR loan, a 25% tax rate, an energy profile, a five-variant
sensitivity spec, and a 200-run Monte Carlo block — a positive-NPV base
case, deliberately contrasting with the failing worked example in
[methodology.md](methodology.md).

| Block | Meaning |
|:------|:--------|
| `schema_version` | Always `1`. |
| `asset` | Name, project life, capex, revenue streams, fixed opex, escalations, discount rate. |
| `loan` | Principal, rate, and tenor of a single annuity loan. |
| `fiscal` | Tax rate, straight-line depreciation years, optional capital grant. |
| `energy` | Year-1 energy and degradation, enabling the levelized cost. |
| `sensitivity` | An ordered list of one-at-a-time variants. |
| `monte_carlo` | Runs, the mandatory seed, and one multiplier distribution per uncertain input. |

All rates and escalations are plain fractions, so `0.07` is seven
percent. Distributions are objects with a `kind` of `normal`, `uniform`,
or `triangular` and that kind's parameters — the same closed set the
Monte Carlo layer documents. The seed is required in the file for the
same reason it is required in the code: an unseeded simulation cannot be
re-run to the same numbers, so none of its figures can be checked.

Loading is deliberately strict. The file has a one-megabyte cap,
duplicate JSON keys are rejected, and an unknown key or a wrong type
fails the whole load with the offending field named — for example
`asset.capex_eur must be a JSON number` or `unknown loan key(s):
balloon_eur`. A scenario either loads completely or not at all. Rules
that span two blocks, such as a loan larger than the capex, are enforced
by the evaluation layers when the scenario runs.

## Commands

```bash
investlab validate --scenario sample-data/scenario.json
investlab run --scenario sample-data/scenario.json --output results
```

`validate` parses the file and prints a JSON summary of what it
contains — the asset, which blocks are present, the variant count, the
Monte Carlo runs and seed — without evaluating anything.

`run` evaluates the base case through the same entry points a direct
library call would use, plus the sensitivity spec and the Monte Carlo
block when present, and writes two artifacts into the output directory:

- `results.json` — every computed number: the base-case metrics, the
  full sensitivity table, and the Monte Carlo summary with its seed, run
  count, and the raw per-run values, so any summary figure can be
  recomputed and checked.
- `report.md` — a short committee-style report: the asset in two
  sentences, the assumptions, the base case, the sensitivity table, the
  Monte Carlo percentiles with the seed stated, and the caveats.

Both artifacts render from one evaluation, so they cannot disagree, and
neither embeds a timestamp: the same scenario file always produces
byte-identical output. Writes are staged next to their targets and
published with atomic replaces, and an output directory that already
holds results is never overwritten unless `--force` is passed.

## Conventions the numbers follow

The MIRR uses the asset's discount rate as both the finance and the
reinvestment rate. With fiscal rules the sensitivity table shows
after-tax project metrics and the Monte Carlo collects the after-tax
equity view; without them, the pre-tax equivalents. These are the same
conventions the sensitivity and Monte Carlo layers document — the CLI
adds no arithmetic of its own.
