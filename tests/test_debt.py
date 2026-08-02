from __future__ import annotations

import unittest

from investlab.debt import Loan, build_amortization, evaluate_financed_project
from investlab.engine import evaluate_project
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


class LoanTests(unittest.TestCase):
    def test_annuity_factor_and_payment_match_the_docs(self) -> None:
        loan = worked_loan()
        # 0.06 / (1 - 1.06^-5) = 0.237396
        self.assertAlmostEqual(loan.annuity_payment_eur / loan.principal_eur, 0.237396, places=6)
        self.assertAlmostEqual(loan.annuity_payment_eur, 142_437.84, places=2)

    def test_a_zero_rate_loan_repays_in_equal_parts(self) -> None:
        loan = Loan(principal_eur=100_000.0, rate_fraction=0.0, tenor_years=4)
        self.assertEqual(loan.annuity_payment_eur, 25_000.0)
        rows = build_amortization(loan)
        self.assertEqual([row.interest_eur for row in rows], [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(rows[-1].closing_balance_eur, 0.0)

    def test_principal_must_be_positive_and_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "principal_eur must be greater than zero"):
            Loan(principal_eur=0.0, rate_fraction=0.06, tenor_years=5)
        with self.assertRaisesRegex(ValueError, "principal_eur must be finite"):
            Loan(principal_eur=float("inf"), rate_fraction=0.06, tenor_years=5)

    def test_rate_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "rate_fraction"):
            Loan(principal_eur=1.0, rate_fraction=-0.01, tenor_years=5)
        with self.assertRaisesRegex(ValueError, "rate_fraction"):
            Loan(principal_eur=1.0, rate_fraction=1.5, tenor_years=5)
        with self.assertRaisesRegex(ValueError, "rate_fraction must be finite"):
            Loan(principal_eur=1.0, rate_fraction=float("nan"), tenor_years=5)

    def test_tenor_must_be_an_integer_between_1_and_50(self) -> None:
        with self.assertRaisesRegex(ValueError, "tenor_years must be an integer"):
            Loan(principal_eur=1.0, rate_fraction=0.06, tenor_years=5.0)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "tenor_years must be an integer"):
            Loan(principal_eur=1.0, rate_fraction=0.06, tenor_years=True)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            Loan(principal_eur=1.0, rate_fraction=0.06, tenor_years=0)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            Loan(principal_eur=1.0, rate_fraction=0.06, tenor_years=51)


class AmortizationTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.rows = build_amortization(worked_loan())

    def test_year_one_split(self) -> None:
        row = self.rows[0]
        self.assertEqual(row.opening_balance_eur, 600_000.0)
        self.assertAlmostEqual(row.interest_eur, 36_000.00, places=2)
        self.assertAlmostEqual(row.principal_eur, 106_437.84, places=2)
        self.assertAlmostEqual(row.payment_eur, 142_437.84, places=2)
        self.assertAlmostEqual(row.closing_balance_eur, 493_562.16, places=2)

    def test_year_two_interest_drops_with_the_balance(self) -> None:
        row = self.rows[1]
        self.assertAlmostEqual(row.interest_eur, 29_613.73, places=2)
        self.assertAlmostEqual(row.principal_eur, 112_824.11, places=2)
        self.assertAlmostEqual(row.closing_balance_eur, 380_738.05, places=2)

    def test_final_year_retires_the_balance_exactly(self) -> None:
        row = self.rows[-1]
        self.assertEqual(row.year, 5)
        self.assertAlmostEqual(row.opening_balance_eur, 134_375.32, places=2)
        self.assertAlmostEqual(row.interest_eur, 8_062.52, places=2)
        self.assertAlmostEqual(row.principal_eur, 134_375.32, places=2)
        self.assertEqual(row.closing_balance_eur, 0.0)

    def test_openings_chain_and_principal_sums_to_the_loan(self) -> None:
        for previous, current in zip(self.rows, self.rows[1:], strict=False):
            self.assertEqual(current.opening_balance_eur, previous.closing_balance_eur)
        self.assertAlmostEqual(sum(row.principal_eur for row in self.rows), 600_000.0, places=6)


class FinancedProjectTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.result = evaluate_financed_project(worked_asset(), worked_loan())

    def test_dscr_series_matches_the_docs(self) -> None:
        self.assertEqual([row.year for row in self.result.dscr_rows], [1, 2, 3, 4, 5])
        first = self.result.dscr_rows[0]
        self.assertEqual(first.cfads_eur, 120_000.0)
        self.assertAlmostEqual(first.debt_service_eur, 142_437.84, places=2)
        self.assertAlmostEqual(first.dscr, 0.8425, places=4)
        self.assertAlmostEqual(self.result.dscr_rows[-1].dscr, 0.9119, places=4)

    def test_the_minimum_dscr_year_is_flagged(self) -> None:
        minimum = self.result.minimum_dscr_row
        self.assertIsNotNone(minimum)
        assert minimum is not None
        self.assertEqual(minimum.year, 1)
        self.assertAlmostEqual(minimum.dscr, 0.8425, places=4)

    def test_equity_cash_flows_match_the_docs(self) -> None:
        equity = self.result.equity_cash_flows_eur
        self.assertEqual(len(equity), 11)
        self.assertEqual(equity[0], -400_000.0)
        self.assertAlmostEqual(equity[1], -22_437.84, places=2)
        self.assertAlmostEqual(equity[5], -12_545.98, places=2)
        self.assertAlmostEqual(equity[6], 132_489.70, places=2)
        self.assertAlmostEqual(equity[10], 143_411.11, places=2)

    def test_equity_npv_and_irr_match_the_docs(self) -> None:
        self.assertAlmostEqual(self.result.equity_npv_eur, -97_973.55, places=2)
        self.assertIsNotNone(self.result.equity_irr_fraction)
        assert self.result.equity_irr_fraction is not None
        self.assertAlmostEqual(self.result.equity_irr_fraction, 0.047013, places=6)

    def test_the_project_view_is_embedded_unchanged(self) -> None:
        unlevered = evaluate_project(worked_asset())
        self.assertEqual(self.result.project.npv_eur, unlevered.npv_eur)
        self.assertEqual(self.result.project.cash_flows_eur, unlevered.cash_flows_eur)


class UndrawnPathTests(unittest.TestCase):
    def test_no_loan_reproduces_the_unlevered_project_exactly(self) -> None:
        financed = evaluate_financed_project(worked_asset())
        unlevered = evaluate_project(worked_asset())
        self.assertIsNone(financed.loan)
        self.assertEqual(financed.amortization, ())
        self.assertEqual(financed.dscr_rows, ())
        self.assertIsNone(financed.minimum_dscr_row)
        self.assertEqual(financed.equity_cash_flows_eur, unlevered.cash_flows_eur)
        self.assertEqual(financed.equity_npv_eur, unlevered.npv_eur)
        self.assertEqual(financed.equity_irr_fraction, unlevered.irr_fraction)


class FinancingValidationTests(unittest.TestCase):
    def test_principal_must_not_exceed_capex(self) -> None:
        loan = Loan(principal_eur=1_000_001.0, rate_fraction=0.06, tenor_years=5)
        with self.assertRaisesRegex(ValueError, "must not exceed the asset capex_eur"):
            evaluate_financed_project(worked_asset(), loan)

    def test_tenor_must_not_exceed_project_life(self) -> None:
        loan = Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=11)
        with self.assertRaisesRegex(ValueError, "must not exceed the asset project_life_years"):
            evaluate_financed_project(worked_asset(), loan)

    def test_a_full_tenor_loan_covers_every_operating_year(self) -> None:
        loan = Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=10)
        result = evaluate_financed_project(worked_asset(), loan)
        self.assertEqual(len(result.dscr_rows), 10)
        self.assertEqual(result.amortization[-1].closing_balance_eur, 0.0)


if __name__ == "__main__":
    unittest.main()
