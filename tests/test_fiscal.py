from __future__ import annotations

import unittest

from investlab.debt import Loan, evaluate_financed_project
from investlab.engine import evaluate_project
from investlab.fiscal import Fiscal, evaluate_after_tax
from investlab.models import Asset, RevenueStream


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


def worked_loan() -> Loan:
    return Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=5)


def worked_fiscal() -> Fiscal:
    return Fiscal(tax_rate_fraction=0.25, depreciation_years=10, grant_eur=100_000.0)


def fiscal(**overrides: object) -> Fiscal:
    fields: dict[str, object] = {
        "tax_rate_fraction": 0.25,
        "depreciation_years": 10,
        "grant_eur": 100_000.0,
    }
    fields.update(overrides)
    return Fiscal(**fields)  # type: ignore[arg-type]


class FiscalValidationTests(unittest.TestCase):
    def test_a_zero_rate_and_zero_grant_are_valid(self) -> None:
        zero = Fiscal(tax_rate_fraction=0.0, depreciation_years=1)
        self.assertEqual(zero.grant_eur, 0.0)

    def test_tax_rate_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "tax_rate_fraction"):
            fiscal(tax_rate_fraction=-0.01)
        with self.assertRaisesRegex(ValueError, "tax_rate_fraction"):
            fiscal(tax_rate_fraction=1.0)
        with self.assertRaisesRegex(ValueError, "tax_rate_fraction must be finite"):
            fiscal(tax_rate_fraction=float("nan"))

    def test_depreciation_years_must_be_an_integer_between_1_and_50(self) -> None:
        with self.assertRaisesRegex(ValueError, "depreciation_years must be an integer"):
            fiscal(depreciation_years=10.0)
        with self.assertRaisesRegex(ValueError, "depreciation_years must be an integer"):
            fiscal(depreciation_years=True)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            fiscal(depreciation_years=0)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            fiscal(depreciation_years=51)

    def test_grant_must_be_non_negative_and_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "grant_eur must be greater than or equal"):
            fiscal(grant_eur=-1.0)
        with self.assertRaisesRegex(ValueError, "grant_eur must be finite"):
            fiscal(grant_eur=float("inf"))

    def test_depreciation_must_not_outlive_the_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not exceed the asset project_life_years"):
            evaluate_after_tax(worked_asset(), fiscal(depreciation_years=11))

    def test_grant_must_be_below_the_capex(self) -> None:
        with self.assertRaisesRegex(ValueError, "grant_eur must be less than the asset capex"):
            evaluate_after_tax(worked_asset(), fiscal(grant_eur=1_000_000.0))
        with self.assertRaisesRegex(ValueError, "grant_eur must be less than the asset capex"):
            evaluate_after_tax(worked_asset(), fiscal(grant_eur=1_000_001.0))


class ZeroTaxPathTests(unittest.TestCase):
    """A zero rate and no grant must reproduce the pre-tax numbers exactly."""

    def test_the_unlevered_project_is_reproduced_exactly(self) -> None:
        result = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.0, depreciation_years=10)
        )
        pre = evaluate_project(worked_asset())
        self.assertEqual(result.after_tax_cash_flows_eur, pre.cash_flows_eur)
        self.assertEqual(result.after_tax_npv_eur, pre.npv_eur)
        self.assertEqual(result.after_tax_irr_fraction, pre.irr_fraction)
        self.assertEqual(result.after_tax_simple_payback_years, pre.simple_payback_years)
        self.assertEqual(result.after_tax_discounted_payback_years, pre.discounted_payback_years)
        self.assertEqual(result.after_tax_equity_cash_flows_eur, pre.cash_flows_eur)
        self.assertEqual([row.tax_eur for row in result.rows], [0.0] * 10)

    def test_the_levered_equity_is_reproduced_exactly(self) -> None:
        result = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.0, depreciation_years=10), worked_loan()
        )
        pre = evaluate_financed_project(worked_asset(), worked_loan())
        self.assertEqual(result.after_tax_equity_cash_flows_eur, pre.equity_cash_flows_eur)
        self.assertEqual(result.after_tax_equity_npv_eur, pre.equity_npv_eur)
        self.assertEqual(result.after_tax_equity_irr_fraction, pre.equity_irr_fraction)
        self.assertEqual(result.after_tax_cash_flows_eur, pre.project.cash_flows_eur)
        self.assertEqual(result.after_tax_npv_eur, pre.project.npv_eur)


class WorkedFiscalTableTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.result = evaluate_after_tax(worked_asset(), worked_fiscal(), worked_loan())

    def test_the_grant_reduces_the_depreciable_base(self) -> None:
        # (1,000,000 - 100,000) / 10 = 90,000 in every operating year.
        self.assertEqual([row.depreciation_eur for row in self.result.rows], [90_000.0] * 10)

    def test_year_one_runs_a_loss_and_pays_no_tax(self) -> None:
        row = self.result.rows[0]
        self.assertEqual(row.operating_result_eur, 120_000.0)
        self.assertAlmostEqual(row.interest_eur, 36_000.00, places=2)
        # 120,000 - 90,000 - 36,000 = -6,000
        self.assertAlmostEqual(row.taxable_result_eur, -6_000.00, places=2)
        self.assertEqual(row.loss_used_eur, 0.0)
        self.assertEqual(row.taxable_base_eur, 0.0)
        self.assertEqual(row.tax_eur, 0.0)
        self.assertAlmostEqual(row.loss_carryforward_eur, 6_000.00, places=2)

    def test_year_two_is_absorbed_by_the_carried_loss(self) -> None:
        row = self.result.rows[1]
        # 122,400 - 90,000 - 29,613.73 = 2,786.27, fully offset by the loss.
        self.assertAlmostEqual(row.taxable_result_eur, 2_786.27, places=2)
        self.assertAlmostEqual(row.loss_used_eur, 2_786.27, places=2)
        self.assertEqual(row.taxable_base_eur, 0.0)
        self.assertEqual(row.tax_eur, 0.0)
        self.assertAlmostEqual(row.loss_carryforward_eur, 3_213.73, places=2)

    def test_taxes_first_become_payable_in_year_three(self) -> None:
        row = self.result.rows[2]
        # 124,848 - 90,000 - 22,844.28 = 12,003.72, less 3,213.73 of losses.
        self.assertAlmostEqual(row.taxable_result_eur, 12_003.72, places=2)
        self.assertAlmostEqual(row.loss_used_eur, 3_213.73, places=2)
        self.assertAlmostEqual(row.taxable_base_eur, 8_789.99, places=2)
        self.assertAlmostEqual(row.tax_eur, 2_197.50, places=2)
        self.assertEqual(row.loss_carryforward_eur, 0.0)
        self.assertEqual([earlier.tax_eur for earlier in self.result.rows[:2]], [0.0, 0.0])

    def test_the_middle_years_match_the_docs(self) -> None:
        self.assertAlmostEqual(self.result.rows[3].tax_eur, 5_419.07, places=2)
        self.assertAlmostEqual(self.result.rows[4].tax_eur, 7_957.33, places=2)
        # Year 6 deducts depreciation only: the loan is repaid.
        self.assertEqual(self.result.rows[5].interest_eur, 0.0)
        self.assertAlmostEqual(self.result.rows[5].taxable_result_eur, 42_489.70, places=2)
        self.assertAlmostEqual(self.result.rows[5].tax_eur, 10_622.42, places=2)

    def test_the_final_year_and_the_total_tax_match_the_docs(self) -> None:
        row = self.result.rows[-1]
        self.assertAlmostEqual(row.taxable_result_eur, 53_411.11, places=2)
        self.assertAlmostEqual(row.tax_eur, 13_352.78, places=2)
        self.assertAlmostEqual(sum(r.tax_eur for r in self.result.rows), 75_444.33, places=2)

    def test_after_tax_project_metrics_match_the_docs(self) -> None:
        self.assertEqual(self.result.after_tax_cash_flows_eur[0], -900_000.0)
        self.assertAlmostEqual(self.result.after_tax_cash_flows_eur[3], 122_650.50, places=2)
        self.assertAlmostEqual(self.result.after_tax_npv_eur, -72_657.23, places=2)
        self.assertIsNotNone(self.result.after_tax_irr_fraction)
        assert self.result.after_tax_irr_fraction is not None
        self.assertAlmostEqual(self.result.after_tax_irr_fraction, 0.061952, places=6)
        self.assertIsNotNone(self.result.after_tax_simple_payback_years)
        assert self.result.after_tax_simple_payback_years is not None
        self.assertAlmostEqual(self.result.after_tax_simple_payback_years, 7.3604, places=4)
        self.assertIsNone(self.result.after_tax_discounted_payback_years)

    def test_after_tax_equity_metrics_match_the_docs(self) -> None:
        equity = self.result.after_tax_equity_cash_flows_eur
        self.assertEqual(equity[0], -300_000.0)
        self.assertAlmostEqual(equity[1], -22_437.84, places=2)
        self.assertAlmostEqual(equity[3], -19_787.34, places=2)
        self.assertAlmostEqual(self.result.after_tax_equity_npv_eur, -41_370.23, places=2)
        self.assertIsNotNone(self.result.after_tax_equity_irr_fraction)
        assert self.result.after_tax_equity_irr_fraction is not None
        self.assertAlmostEqual(self.result.after_tax_equity_irr_fraction, 0.063145, places=6)


class EffectIsolationTests(unittest.TestCase):
    def test_tax_alone_charges_the_full_depreciated_base(self) -> None:
        result = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.25, depreciation_years=10)
        )
        # 120,000 - 1,000,000 / 10 = 20,000, taxed at 25% from year one.
        self.assertEqual(result.rows[0].depreciation_eur, 100_000.0)
        self.assertEqual(result.rows[0].taxable_result_eur, 20_000.0)
        self.assertEqual(result.rows[0].tax_eur, 5_000.0)
        self.assertEqual([row.loss_carryforward_eur for row in result.rows], [0.0] * 10)
        self.assertAlmostEqual(result.after_tax_npv_eur, -179_193.38, places=2)
        pre = evaluate_project(worked_asset())
        self.assertLess(result.after_tax_npv_eur, pre.npv_eur)

    def test_a_grant_alone_only_shifts_year_zero(self) -> None:
        result = evaluate_after_tax(
            worked_asset(),
            Fiscal(tax_rate_fraction=0.0, depreciation_years=10, grant_eur=100_000.0),
        )
        pre = evaluate_project(worked_asset())
        self.assertEqual(result.after_tax_cash_flows_eur[0], -900_000.0)
        self.assertEqual(result.after_tax_cash_flows_eur[1:], pre.cash_flows_eur[1:])
        self.assertAlmostEqual(result.after_tax_npv_eur, pre.npv_eur + 100_000.0, places=6)
        self.assertEqual([row.tax_eur for row in result.rows], [0.0] * 10)

    def test_a_shorter_depreciation_front_loads_the_shield(self) -> None:
        five = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.25, depreciation_years=5)
        )
        ten = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.25, depreciation_years=10)
        )
        self.assertEqual(five.rows[0].depreciation_eur, 200_000.0)
        self.assertEqual(five.rows[5].depreciation_eur, 0.0)
        # Every loss is recovered later, so only the timing differs: the
        # total tax is identical and the earlier shield wins on NPV.
        self.assertAlmostEqual(
            sum(row.tax_eur for row in five.rows),
            sum(row.tax_eur for row in ten.rows),
            places=6,
        )
        self.assertGreater(five.after_tax_npv_eur, ten.after_tax_npv_eur)

    def test_interest_is_deductible_and_lowers_the_tax(self) -> None:
        levered = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.25, depreciation_years=10), worked_loan()
        )
        unlevered = evaluate_after_tax(
            worked_asset(), Fiscal(tax_rate_fraction=0.25, depreciation_years=10)
        )
        # Year 1 taxable drops by exactly the 36,000 of interest.
        self.assertAlmostEqual(
            unlevered.rows[0].taxable_result_eur - levered.rows[0].taxable_result_eur,
            36_000.00,
            places=2,
        )
        self.assertGreater(levered.rows[0].loss_carryforward_eur, 0.0)
        self.assertLess(
            sum(row.tax_eur for row in levered.rows),
            sum(row.tax_eur for row in unlevered.rows),
        )


class CarryforwardTests(unittest.TestCase):
    """Losses accumulate over several years and release gradually."""

    def setUp(self) -> None:
        asset = Asset(
            name="Carryforward",
            project_life_years=4,
            capex_eur=100_000.0,
            revenues=(RevenueStream(name="sales", year_one_amount_eur=30_000.0),),
            fixed_opex_eur=0.0,
            discount_rate_fraction=0.0,
        )
        self.rows = evaluate_after_tax(
            asset, Fiscal(tax_rate_fraction=0.25, depreciation_years=2)
        ).rows

    def test_two_loss_years_stack_the_pool(self) -> None:
        # 30,000 - 100,000 / 2 = -20,000 in each of the first two years.
        self.assertEqual(self.rows[0].taxable_result_eur, -20_000.0)
        self.assertEqual(self.rows[0].loss_carryforward_eur, 20_000.0)
        self.assertEqual(self.rows[1].loss_carryforward_eur, 40_000.0)

    def test_year_three_is_fully_sheltered(self) -> None:
        row = self.rows[2]
        self.assertEqual(row.taxable_result_eur, 30_000.0)
        self.assertEqual(row.loss_used_eur, 30_000.0)
        self.assertEqual(row.taxable_base_eur, 0.0)
        self.assertEqual(row.tax_eur, 0.0)
        self.assertEqual(row.loss_carryforward_eur, 10_000.0)

    def test_year_four_uses_the_remainder_and_pays_tax(self) -> None:
        row = self.rows[3]
        self.assertEqual(row.loss_used_eur, 10_000.0)
        self.assertEqual(row.taxable_base_eur, 20_000.0)
        self.assertEqual(row.tax_eur, 5_000.0)
        self.assertEqual(row.loss_carryforward_eur, 0.0)


class ResultShapeTests(unittest.TestCase):
    def test_the_financed_view_is_embedded_unchanged(self) -> None:
        result = evaluate_after_tax(worked_asset(), worked_fiscal(), worked_loan())
        pre = evaluate_financed_project(worked_asset(), worked_loan())
        self.assertEqual(result.financed.project.npv_eur, pre.project.npv_eur)
        self.assertEqual(result.financed.equity_cash_flows_eur, pre.equity_cash_flows_eur)
        self.assertEqual(result.financed.equity_npv_eur, pre.equity_npv_eur)

    def test_one_fiscal_row_per_operating_year(self) -> None:
        result = evaluate_after_tax(worked_asset(), worked_fiscal(), worked_loan())
        self.assertEqual([row.year for row in result.rows], list(range(1, 11)))
        self.assertEqual(len(result.after_tax_cash_flows_eur), 11)
        self.assertEqual(len(result.after_tax_equity_cash_flows_eur), 11)
        self.assertEqual(result.fiscal, worked_fiscal())


if __name__ == "__main__":
    unittest.main()
