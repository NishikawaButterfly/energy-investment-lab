"""The reporting layer: evaluate a scenario once, render every artifact from it.

``evaluate_scenario`` runs the base case through the existing entry
points, plus the sensitivity spec and the Monte Carlo block when the
scenario carries them, and returns one frozen evaluation.
``results_payload`` and ``render_report`` both read that evaluation and
never recompute a number, so the JSON results and the Markdown report
cannot disagree. Neither function touches a file, prints, or looks at
the clock: the same scenario always renders the same bytes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from investlab.debt import FinancedResult, evaluate_financed_project
from investlab.fiscal import FiscalResult, evaluate_after_tax
from investlab.io import SCENARIO_SCHEMA_VERSION, Scenario
from investlab.metrics import levelized_cost, modified_internal_rate_of_return
from investlab.montecarlo import MonteCarloResult, run_monte_carlo
from investlab.sensitivity import SensitivityResult, run_sensitivity


@dataclass(frozen=True, slots=True)
class ScenarioEvaluation:
    """Everything one scenario evaluates to, in one frozen object.

    The MIRR covers the after-tax project cash flows when fiscal rules
    exist and the pre-tax project flows otherwise, with the asset's
    discount rate as both the finance and the reinvestment rate — the
    same convention the sensitivity layer documents.
    """

    scenario: Scenario
    financed: FinancedResult
    fiscal_result: FiscalResult | None
    mirr_fraction: float | None
    lcoe_eur_per_mwh: float | None
    sensitivity: SensitivityResult | None
    monte_carlo: MonteCarloResult | None


def evaluate_scenario(scenario: Scenario) -> ScenarioEvaluation:
    """Evaluate everything the scenario carries through the existing layers.

    The base case always runs; the sensitivity spec and the Monte Carlo
    block run only when present. Every number comes from the same entry
    points a direct library call would use.
    """

    asset, loan, fiscal = scenario.asset, scenario.loan, scenario.fiscal
    fiscal_result = evaluate_after_tax(asset, fiscal, loan) if fiscal is not None else None
    financed = (
        fiscal_result.financed
        if fiscal_result is not None
        else evaluate_financed_project(asset, loan)
    )
    cash_flows = (
        fiscal_result.after_tax_cash_flows_eur
        if fiscal_result is not None
        else financed.project.cash_flows_eur
    )
    return ScenarioEvaluation(
        scenario=scenario,
        financed=financed,
        fiscal_result=fiscal_result,
        mirr_fraction=modified_internal_rate_of_return(
            cash_flows, asset.discount_rate_fraction, asset.discount_rate_fraction
        ),
        lcoe_eur_per_mwh=(
            levelized_cost(asset, scenario.energy) if scenario.energy is not None else None
        ),
        sensitivity=(
            run_sensitivity(asset, scenario.sensitivity, loan, fiscal)
            if scenario.sensitivity is not None
            else None
        ),
        monte_carlo=(
            run_monte_carlo(
                asset,
                scenario.monte_carlo.distributions,
                scenario.monte_carlo.runs,
                scenario.monte_carlo.seed,
                loan=loan,
                fiscal=fiscal,
            )
            if scenario.monte_carlo is not None
            else None
        ),
    )


def results_payload(evaluation: ScenarioEvaluation) -> dict[str, Any]:
    """Every computed number as one JSON-ready dictionary.

    The Monte Carlo section keeps the seed, the run count, and the raw
    per-run values, so any summary figure can be recomputed and checked.
    """

    financed = evaluation.financed
    project = financed.project
    base: dict[str, Any] = {
        "project": {
            "npv_eur": project.npv_eur,
            "irr_fraction": project.irr_fraction,
            "simple_payback_years": project.simple_payback_years,
            "discounted_payback_years": project.discounted_payback_years,
        },
        "mirr_fraction": evaluation.mirr_fraction,
        "equity": None,
        "after_tax": None,
        "minimum_dscr": None,
        "lcoe_eur_per_mwh": evaluation.lcoe_eur_per_mwh,
    }
    if financed.loan is not None:
        base["equity"] = {
            "npv_eur": financed.equity_npv_eur,
            "irr_fraction": financed.equity_irr_fraction,
        }
    if financed.minimum_dscr_row is not None:
        base["minimum_dscr"] = asdict(financed.minimum_dscr_row)
    if evaluation.fiscal_result is not None:
        taxed = evaluation.fiscal_result
        base["after_tax"] = {
            "npv_eur": taxed.after_tax_npv_eur,
            "irr_fraction": taxed.after_tax_irr_fraction,
            "simple_payback_years": taxed.after_tax_simple_payback_years,
            "discounted_payback_years": taxed.after_tax_discounted_payback_years,
            "equity_npv_eur": taxed.after_tax_equity_npv_eur,
            "equity_irr_fraction": taxed.after_tax_equity_irr_fraction,
        }
    payload: dict[str, Any] = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "asset_name": evaluation.scenario.asset.name,
        "units": {
            "money": "EUR",
            "rates": "fraction per year",
            "payback": "years",
            "energy": "MWh",
            "levelized_cost": "EUR/MWh",
        },
        "base": base,
        "sensitivity": None,
        "monte_carlo": None,
    }
    if evaluation.sensitivity is not None:
        payload["sensitivity"] = {
            "run_count": len(evaluation.sensitivity.rows),
            "rows": [asdict(row) for row in evaluation.sensitivity.rows],
        }
    if evaluation.monte_carlo is not None:
        simulation = evaluation.monte_carlo
        payload["monte_carlo"] = {
            "seed": simulation.seed,
            "runs": simulation.runs,
            "npv_mean_eur": simulation.npv_mean_eur,
            "npv_stddev_eur": simulation.npv_stddev_eur,
            "npv_percentiles_eur": asdict(simulation.npv_percentiles_eur),
            "probability_npv_negative": simulation.probability_npv_negative,
            "irr_percentiles_fraction": (
                asdict(simulation.irr_percentiles_fraction)
                if simulation.irr_percentiles_fraction is not None
                else None
            ),
            "irr_defined_count": simulation.irr_defined_count,
            "irr_undefined_count": simulation.irr_undefined_count,
            "npv_values_eur": list(simulation.npv_values_eur),
            "irr_values_fraction": list(simulation.irr_values_fraction),
        }
    return payload


def _eur(value: float) -> str:
    return f"{value:,.0f} EUR"


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fraction_cell(value: float | None) -> str:
    return "—" if value is None else _percent(value)


def _payback_cell(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _spoken_list(items: list[str]) -> str:
    *head, tail = items
    if not head:
        return tail
    if len(head) == 1:
        return f"{head[0]} and {tail}"
    return ", ".join(head) + ", and " + tail


def _table(header: tuple[str, ...], rows: Sequence[tuple[str, ...]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "|".join([":---"] + ["---:"] * (len(header) - 1)) + "|")
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _asset_paragraph(scenario: Scenario) -> str:
    asset = scenario.asset
    streams = ", ".join(stream.name for stream in asset.revenues)
    first = (
        f"{asset.name} spends {_eur(asset.capex_eur)} at year 0 and operates for "
        f"{asset.project_life_years} years, earning revenue from {streams} against "
        "a fixed operating cost."
    )
    loan, fiscal = scenario.loan, scenario.fiscal
    if loan is not None and fiscal is not None:
        second = (
            f"The case is financed with a {_eur(loan.principal_eur)} loan at "
            f"{_percent(loan.rate_fraction)} over {loan.tenor_years} years and taxed at "
            f"{_percent(fiscal.tax_rate_fraction)} with straight-line depreciation over "
            f"{fiscal.depreciation_years} years."
        )
    elif loan is not None:
        second = (
            f"The case is financed with a {_eur(loan.principal_eur)} loan at "
            f"{_percent(loan.rate_fraction)} over {loan.tenor_years} years, "
            "with no fiscal rules applied."
        )
    elif fiscal is not None:
        second = (
            f"The case carries no debt and is taxed at {_percent(fiscal.tax_rate_fraction)} "
            f"with straight-line depreciation over {fiscal.depreciation_years} years."
        )
    else:
        second = "The case carries no debt and no fiscal rules, so every view is the project's."
    return f"{first} {second}"


def _assumption_rows(scenario: Scenario) -> list[tuple[str, ...]]:
    asset = scenario.asset
    rows: list[tuple[str, ...]] = [
        ("Capex", _eur(asset.capex_eur)),
        ("Project life", f"{asset.project_life_years} years"),
    ]
    for stream in asset.revenues:
        rows.append((f"Revenue, {stream.name} (year 1)", _eur(stream.year_one_amount_eur)))
        rows.append(
            (
                f"Revenue escalation, {stream.name}",
                f"{_percent(stream.escalation_fraction_per_year)} per year",
            )
        )
    rows.append(("Fixed opex (year 1)", _eur(asset.fixed_opex_eur)))
    rows.append(
        ("Opex escalation", f"{_percent(asset.opex_escalation_fraction_per_year)} per year")
    )
    rows.append(("Discount rate", _percent(asset.discount_rate_fraction)))
    if scenario.loan is not None:
        loan = scenario.loan
        rows.append(("Loan principal", _eur(loan.principal_eur)))
        rows.append(("Loan rate", _percent(loan.rate_fraction)))
        rows.append(("Loan tenor", f"{loan.tenor_years} years"))
    if scenario.fiscal is not None:
        fiscal = scenario.fiscal
        rows.append(("Tax rate", _percent(fiscal.tax_rate_fraction)))
        rows.append(("Depreciation", f"straight-line over {fiscal.depreciation_years} years"))
        rows.append(("Capital grant", _eur(fiscal.grant_eur) if fiscal.grant_eur else "none"))
    if scenario.energy is not None:
        energy = scenario.energy
        rows.append(("Energy (year 1)", f"{energy.year_one_energy_mwh:,.0f} MWh"))
        rows.append(
            ("Energy degradation", f"{_percent(energy.degradation_fraction_per_year)} per year")
        )
    return rows


def _base_case_lines(evaluation: ScenarioEvaluation) -> list[str]:
    financed = evaluation.financed
    project = financed.project
    taxed = evaluation.fiscal_result
    rows: list[tuple[str, ...]] = [
        ("Project NPV (pre-tax)", _eur(project.npv_eur)),
        ("Project IRR (pre-tax)", _fraction_cell(project.irr_fraction)),
    ]
    if financed.loan is not None:
        rows.append(("Equity NPV (pre-tax)", _eur(financed.equity_npv_eur)))
        rows.append(("Equity IRR (pre-tax)", _fraction_cell(financed.equity_irr_fraction)))
    if taxed is not None:
        rows.append(("Project NPV (after tax)", _eur(taxed.after_tax_npv_eur)))
        rows.append(("Project IRR (after tax)", _fraction_cell(taxed.after_tax_irr_fraction)))
        rows.append(("Equity NPV (after tax)", _eur(taxed.after_tax_equity_npv_eur)))
        rows.append(
            ("Equity IRR (after tax)", _fraction_cell(taxed.after_tax_equity_irr_fraction))
        )
        simple = taxed.after_tax_simple_payback_years
        discounted = taxed.after_tax_discounted_payback_years
        mirr_label = "MIRR (after-tax project flows)"
        payback_suffix = "after tax"
    else:
        simple = project.simple_payback_years
        discounted = project.discounted_payback_years
        mirr_label = "MIRR (project flows)"
        payback_suffix = "pre-tax"
    rows.append((mirr_label, _fraction_cell(evaluation.mirr_fraction)))
    simple_cell = "never" if simple is None else f"{simple:.2f} years"
    discounted_cell = "never" if discounted is None else f"{discounted:.2f} years"
    rows.append((f"Simple payback ({payback_suffix})", simple_cell))
    rows.append((f"Discounted payback ({payback_suffix})", discounted_cell))
    minimum = financed.minimum_dscr_row
    if minimum is not None:
        rows.append(("Minimum DSCR", f"{minimum.dscr:.2f} (year {minimum.year})"))
    if evaluation.lcoe_eur_per_mwh is not None:
        rows.append(("Levelized cost of energy", f"{evaluation.lcoe_eur_per_mwh:.2f} EUR/MWh"))

    rate = evaluation.scenario.asset.discount_rate_fraction
    headline_npv = taxed.after_tax_npv_eur if taxed is not None else project.npv_eur
    basis = "after-tax project" if taxed is not None else "project"
    verdict = "clears" if headline_npv > 0 else "does not clear"
    lines = _table(("Metric", "Value"), rows)
    lines.append("")
    lines.append(
        f"The {basis} NPV is {_eur(headline_npv)} at the {_percent(rate)} discount "
        f"rate, so the case {verdict} its hurdle. The MIRR uses that same rate as "
        "both the finance and the reinvestment rate."
    )
    return lines


def _sensitivity_lines(evaluation: ScenarioEvaluation) -> list[str]:
    result = evaluation.sensitivity
    if result is None:
        return ["The scenario requests no sensitivity variants."]
    levered = evaluation.financed.loan is not None
    basis = "after-tax project" if evaluation.fiscal_result is not None else "pre-tax project"
    header: tuple[str, ...] = ("Variant", "NPV", "IRR", "MIRR", "Simple payback")
    if levered:
        header = (*header, "Min DSCR")
    rows: list[tuple[str, ...]] = []
    for row in result.rows:
        cells: tuple[str, ...] = (
            row.label.replace("*", "\\*"),
            _eur(row.npv_eur),
            _fraction_cell(row.irr_fraction),
            _fraction_cell(row.mirr_fraction),
            _payback_cell(row.simple_payback_years),
        )
        if levered:
            dscr = "—" if row.minimum_dscr is None else f"{row.minimum_dscr:.2f}"
            cells = (*cells, dscr)
        rows.append(cells)
    lines = [
        (
            "Each variant changes exactly one parameter from the base case and reruns "
            f"the same evaluation. The figures are {basis} metrics; paybacks are in years."
        ),
        "",
    ]
    lines.extend(_table(header, rows))
    return lines


def _monte_carlo_lines(evaluation: ScenarioEvaluation) -> list[str]:
    simulation = evaluation.monte_carlo
    block = evaluation.scenario.monte_carlo
    if simulation is None or block is None:
        return ["The scenario requests no Monte Carlo simulation."]
    distributions = block.distributions
    varied = []
    if distributions.capex is not None:
        varied.append("the capex")
    varied.extend(f"the {name} revenue" for name in distributions.revenue_by_name)
    if distributions.opex is not None:
        varied.append("the opex")
    if evaluation.fiscal_result is not None:
        basis = "after-tax equity"
    elif evaluation.financed.loan is not None:
        basis = "pre-tax equity"
    else:
        basis = "project"
    npv = simulation.npv_percentiles_eur
    irr = simulation.irr_percentiles_fraction
    rows = [
        (
            f"P{level}",
            _eur(getattr(npv, f"p{level}")),
            "—" if irr is None else _percent(getattr(irr, f"p{level}")),
        )
        for level in (5, 25, 50, 75, 95)
    ]
    lines = [
        (
            f"The simulation ran {simulation.runs} times with seed {simulation.seed}, "
            f"varying {_spoken_list(varied)}. The collected figures are the {basis} NPV "
            "and IRR."
        ),
        "",
    ]
    lines.extend(_table(("Percentile", "NPV", "IRR"), rows))
    lines.append("")
    lines.append(
        f"The mean NPV is {_eur(simulation.npv_mean_eur)} with a standard deviation "
        f"of {_eur(simulation.npv_stddev_eur)}. The NPV was negative in "
        f"{_percent(simulation.probability_npv_negative)} of runs, and a unique IRR "
        f"existed in {simulation.irr_defined_count} of {simulation.runs} runs."
    )
    return lines


def render_report(evaluation: ScenarioEvaluation, source_name: str) -> str:
    """Render the committee report as Markdown, deterministically.

    ``source_name`` is the scenario's file name, cited so a reader knows
    which document reproduces the numbers.
    """

    lines: list[str] = [f"# Investment committee report: {evaluation.scenario.asset.name}"]
    lines.append("")
    lines.append(
        f"Prepared by investlab from `{source_name}`. Every figure below is "
        "recomputable from that file alone; the Monte Carlo section states the "
        "seed that reproduces it."
    )
    lines.append("")
    lines.append("## The asset")
    lines.append("")
    lines.append(_asset_paragraph(evaluation.scenario))
    lines.append("")
    lines.append("## Assumptions")
    lines.append("")
    lines.extend(_table(("Item", "Value"), _assumption_rows(evaluation.scenario)))
    lines.append("")
    lines.append("## Base case")
    lines.append("")
    lines.extend(_base_case_lines(evaluation))
    lines.append("")
    lines.append("## Sensitivity")
    lines.append("")
    lines.extend(_sensitivity_lines(evaluation))
    lines.append("")
    lines.append("## Monte Carlo")
    lines.append("")
    lines.extend(_monte_carlo_lines(evaluation))
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Every input in this scenario is fictional; the asset, prices, and costs "
        "model no real project or market."
    )
    lines.append(
        "- The scope is the unlevered project and the levered equity view of a "
        "single asset on an annual grid; nothing finer than a year is represented."
    )
    lines.append(
        "- Inflation has no knob of its own: nominal effects enter only through the "
        "per-stream revenue and opex escalations."
    )
    lines.append("- Nothing in this report is investment advice.")
    lines.append("")
    return "\n".join(lines)
