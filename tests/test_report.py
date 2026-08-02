from __future__ import annotations

import unittest

from investlab.debt import Loan
from investlab.fiscal import Fiscal
from investlab.io import MonteCarloBlock, Scenario
from investlab.models import Asset, RevenueStream
from investlab.montecarlo import Distributions, Uniform
from investlab.report import evaluate_scenario, render_report, results_payload
from investlab.sensitivity import SensitivitySpec, SensitivityVariant


def worked_asset() -> Asset:
    """The asset from the worked example in docs/methodology.md."""

    return Asset(
        name="Worked example",
        project_life_years=10,
        capex_eur=1_000_000.0,
        revenues=(
            RevenueStream(
                name="energy sales",
                year_one_amount_eur=150_000.0,
                escalation_fraction_per_year=0.02,
            ),
        ),
        fixed_opex_eur=30_000.0,
        opex_escalation_fraction_per_year=0.02,
        discount_rate_fraction=0.08,
    )


def scenario_with(
    loan: Loan | None = None,
    fiscal: Fiscal | None = None,
    sensitivity: SensitivitySpec | None = None,
    monte_carlo: MonteCarloBlock | None = None,
) -> Scenario:
    return Scenario(
        asset=worked_asset(),
        loan=loan,
        fiscal=fiscal,
        energy=None,
        sensitivity=sensitivity,
        monte_carlo=monte_carlo,
    )


class UnleveredReportTests(unittest.TestCase):
    def test_the_report_shows_the_worked_example_project_figures(self) -> None:
        evaluation = evaluate_scenario(scenario_with())
        report = render_report(evaluation, source_name="scenario.json")
        self.assertIn("# Investment committee report: Worked example", report)
        self.assertIn(
            "The case carries no debt and no fiscal rules, so every view is the project's.",
            report,
        )
        self.assertIn("| Project NPV (pre-tax) | -129,261 EUR |", report)
        self.assertIn("| Project IRR (pre-tax) | 5.13% |", report)
        self.assertIn("| MIRR (project flows) | ", report)
        self.assertIn("| Simple payback (pre-tax) | 7.78 years |", report)
        self.assertIn("| Discounted payback (pre-tax) | never |", report)
        self.assertIn(
            "The project NPV is -129,261 EUR at the 8.00% discount rate, so the "
            "case does not clear its hurdle.",
            report,
        )
        self.assertIn("The scenario requests no sensitivity variants.", report)
        self.assertIn("The scenario requests no Monte Carlo simulation.", report)
        self.assertNotIn("Minimum DSCR", report)
        self.assertNotIn("Levelized cost", report)

    def test_the_payload_leaves_absent_blocks_as_none(self) -> None:
        payload = results_payload(evaluate_scenario(scenario_with()))
        base = payload["base"]
        self.assertAlmostEqual(base["project"]["npv_eur"], -129_260.55, places=2)
        self.assertIsNone(base["equity"])
        self.assertIsNone(base["after_tax"])
        self.assertIsNone(base["minimum_dscr"])
        self.assertIsNone(base["lcoe_eur_per_mwh"])
        self.assertIsNone(payload["sensitivity"])
        self.assertIsNone(payload["monte_carlo"])


class LeveredReportTests(unittest.TestCase):
    def loan(self) -> Loan:
        return Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=5)

    def test_the_report_shows_the_equity_view_without_fiscal_rules(self) -> None:
        spec = SensitivitySpec(
            variants=(SensitivityVariant(parameter="energy sales", mode="multiplier", value=0.8),)
        )
        evaluation = evaluate_scenario(scenario_with(loan=self.loan(), sensitivity=spec))
        report = render_report(evaluation, source_name="levered.json")
        self.assertIn(
            "The case is financed with a 600,000 EUR loan at 6.00% over 5 years, "
            "with no fiscal rules applied.",
            report,
        )
        self.assertIn("| Equity NPV (pre-tax) | -97,974 EUR |", report)
        self.assertIn("| Equity IRR (pre-tax) | 4.70% |", report)
        self.assertIn("| Minimum DSCR | 0.84 (year 1) |", report)
        self.assertIn("The figures are pre-tax project metrics", report)
        self.assertIn("| Variant | NPV | IRR | MIRR | Simple payback | Min DSCR |", report)
        # The -20% revenue variant never pays back, so its payback cell is a dash.
        self.assertIn("| energy sales\\*0.8 | -346,945 EUR | -0.26% | 3.49% | — | 0.63 |", report)

    def test_a_pre_tax_monte_carlo_collects_the_equity_view(self) -> None:
        block = MonteCarloBlock(
            distributions=Distributions(capex=Uniform(1.0, 1.0)), runs=10, seed=1
        )
        evaluation = evaluate_scenario(scenario_with(loan=self.loan(), monte_carlo=block))
        report = render_report(evaluation, source_name="levered.json")
        self.assertIn(
            "The simulation ran 10 times with seed 1, varying the capex. The "
            "collected figures are the pre-tax equity NPV and IRR.",
            report,
        )
        payload = results_payload(evaluation)
        monte_carlo = payload["monte_carlo"]
        self.assertEqual(monte_carlo["runs"], 10)
        self.assertEqual(monte_carlo["seed"], 1)
        self.assertEqual(len(monte_carlo["npv_values_eur"]), 10)
        # A degenerate distribution reproduces the deterministic equity NPV.
        self.assertAlmostEqual(monte_carlo["npv_percentiles_eur"]["p50"], -97_973.55, places=2)
        self.assertEqual(monte_carlo["npv_stddev_eur"], 0.0)


class TaxedReportTests(unittest.TestCase):
    def test_a_taxed_unlevered_case_names_the_fiscal_rules_and_grant(self) -> None:
        fiscal = Fiscal(tax_rate_fraction=0.25, depreciation_years=10, grant_eur=100_000.0)
        evaluation = evaluate_scenario(scenario_with(fiscal=fiscal))
        report = render_report(evaluation, source_name="taxed.json")
        self.assertIn(
            "The case carries no debt and is taxed at 25.00% with straight-line "
            "depreciation over 10 years.",
            report,
        )
        self.assertIn("| Capital grant | 100,000 EUR |", report)
        self.assertIn("| Project NPV (after tax) | ", report)
        self.assertIn("| Simple payback (after tax) | ", report)
        payload = results_payload(evaluation)
        self.assertIsNotNone(payload["base"]["after_tax"])
        self.assertIsNone(payload["base"]["equity"])

    def test_a_project_basis_monte_carlo_is_labelled_as_such(self) -> None:
        block = MonteCarloBlock(
            distributions=Distributions(opex=Uniform(1.0, 1.0)), runs=10, seed=3
        )
        evaluation = evaluate_scenario(scenario_with(monte_carlo=block))
        report = render_report(evaluation, source_name="plain.json")
        self.assertIn(
            "varying the opex. The collected figures are the project NPV and IRR.", report
        )


if __name__ == "__main__":
    unittest.main()
