# Energy Investment Lab

[![CI](https://github.com/NishikawaButterfly/energy-investment-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/NishikawaButterfly/energy-investment-lab/actions/workflows/ci.yml)

A cash-flow and financing model for energy assets: solar, wind, batteries,
pumped hydro, and the hybrids in between. You describe an asset's costs,
revenues, and financing, and it works out the investment case — NPV, IRR,
payback, debt service — with every intermediate number visible and testable.

This project is young and being built in the open, issue by issue. The plan
is a calculation kernel first (plain Python, no heavy dependencies), then a
CLI, then reporting. Nothing here is investment advice, and every dataset in
this repository is fictional.

## What exists today

The discounting primitives, the asset model, the cash-flow engine (the
year-by-year table, NPV, IRR, simple and discounted payback), the
debt layer (annuity amortization, equity cash flows and returns, DSCR
with the minimum year flagged), and standalone metrics: MIRR with
explicit finance and reinvestment rates, and levelized cost from an
energy profile with degradation (LCOE, or LCOS for storage). The method
and a worked example live in

year-by-year table, NPV, IRR, simple and discounted payback), the debt
layer (annuity amortization, equity cash flows and returns, DSCR with
the minimum year flagged), and the fiscal layer (corporate tax with
straight-line depreciation, capital grants, unlimited loss carryforward,
and the after-tax metrics). The method and a worked example live in
[docs/methodology.md](docs/methodology.md). The CLI and reporting layers
do not exist yet. Watch the
[issues](https://github.com/NishikawaButterfly/energy-investment-lab/issues)
to see what lands next.

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
