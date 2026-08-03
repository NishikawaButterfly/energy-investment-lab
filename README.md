# Energy Investment Lab

[![CI](https://github.com/NishikawaButterfly/energy-investment-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/NishikawaButterfly/energy-investment-lab/actions/workflows/ci.yml)

A cash-flow and financing model for energy assets: solar, wind, batteries,
pumped hydro, and the hybrids in between. You describe an asset's costs,
revenues, and financing, and it works out the investment case — NPV, IRR,
payback, debt service — with every intermediate number visible and testable.

This project is built in the open, issue by issue. It is a calculation
kernel (plain Python, no heavy dependencies) with a CLI and a reproducible
report on top. Nothing here is investment advice, and every dataset in
this repository is fictional.

## What exists today

The discounting primitives, the asset model, the cash-flow engine (the
year-by-year table, NPV, IRR, simple and discounted payback), the debt
layer (annuity amortization, equity cash flows and returns, DSCR with
the minimum year flagged), the fiscal layer (corporate tax with
straight-line depreciation, capital grants, unlimited loss carryforward,
and the after-tax metrics), standalone metrics (MIRR with explicit
finance and reinvestment rates, and levelized cost from an energy
profile with degradation - LCOE, or LCOS for storage), and one-at-a-time
sensitivities (a capped spec of single-parameter variants rerun through
the same evaluations, base row flagged). The method and a worked example
live in [docs/methodology.md](docs/methodology.md). Watch the
[issues](https://github.com/NishikawaButterfly/energy-investment-lab/issues)
to see what lands next.

There is also a seeded Monte Carlo layer: uncertain capex, revenues,
and opex drawn from truncated-normal, uniform, or triangular
distributions, with NPV and IRR percentiles and the probability of a
negative NPV. The seed is a required argument, so every simulation is
reproducible number for number.

On top of the kernel sits the `investlab` CLI: one JSON scenario file
in, `results.json` and a committee-style `report.md` out. The scenario
format and both commands are described in [docs/cli.md](docs/cli.md).

## Usage

Install the package and point the CLI at a scenario file:

```bash
python -m pip install -e .
investlab run --scenario sample-data/scenario.json --output results
```

The run writes `results.json`, with every computed number plus the
Monte Carlo seed and run count, and `report.md`, a short report meant
to be read in a few minutes: the assumptions, the base case, the
sensitivity table, the Monte Carlo percentiles, and the caveats.
`investlab validate --scenario FILE` checks a scenario file without
evaluating it.

## Development

Python 3.12 or newer, no runtime dependencies.

```bash
python -m venv .venv
# Activate .venv with the command for your shell.
python -m pip install -e ".[dev]"
python -m unittest discover -s tests
```

## License

Released under the [MIT License](LICENSE).
