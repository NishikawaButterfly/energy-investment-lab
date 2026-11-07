# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The README intro now describes the CLI and the report as shipped features
  rather than future plans (#18).
- Development tools (coverage, mypy, ruff) updated to newer releases; the
  package still has no runtime dependencies.

### Fixed

- The package version in `pyproject.toml` and `investlab.__version__` now
  matches the v0.1.0 release; the tagged code still reported 0.0.1 (#18).

## [0.1.0] - 2026-08-02

First tagged release: a plain-Python cash-flow and financing kernel for energy
assets, with no runtime dependencies. Every worked example in the docs is
hand-calculated and pinned by tests; 250 tests in total. Nothing here is
investment advice.

### Added

- Year-by-year cash-flow engine with escalated revenues and opex, NPV,
  bisection IRR with a sign-change guard, and fractional paybacks (#9).
- Annuity debt: an amortization table that retires the balance to zero,
  DSCR with its minimum year, and equity NPV and IRR (#9).
- MIRR with explicit finance and reinvestment rates, for project and equity
  flows (#10).
- Levelized cost from a degrading energy profile, as LCOE for generation and
  LCOS for storage (#10).
- Corporate tax with straight-line depreciation, deductible loan interest,
  unlimited loss carryforward, and capital grants (#11).
- One-at-a-time sensitivities, capped at 32 runs, with flat CSV-ready result
  rows (#12).
- Seeded Monte Carlo over capex, revenues, and opex with truncated-normal,
  uniform, or triangular distributions; the seed is required, so every
  simulation is reproducible (#13).
- `investlab run` CLI: one scenario file in, `results.json` and a
  committee-style `report.md` out, byte-identical across runs (#14).
- Methodology and CLI documentation, and the Meadowlark Solar Park sample
  scenario (#9, #14).

[Unreleased]: https://github.com/NishikawaButterfly/energy-investment-lab/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/NishikawaButterfly/energy-investment-lab/releases/tag/v0.1.0
