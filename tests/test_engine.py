from __future__ import annotations

import unittest

from investlab.engine import (
    _payback_years,
    _sign_changes,
    build_year_rows,
    evaluate_project,
    internal_rate_of_return,
)
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


class WorkedExampleTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.result = evaluate_project(worked_asset())

    def test_year_zero_row_carries_the_capex(self) -> None:
        row = self.result.rows[0]
        self.assertEqual(row.year, 0)
        self.assertEqual(row.revenue_eur, 0.0)
        self.assertEqual(row.opex_eur, 0.0)
        self.assertEqual(row.net_cash_flow_eur, -1_000_000.0)
        self.assertEqual(row.discount_factor, 1.0)
        self.assertEqual(row.cumulative_cash_flow_eur, -1_000_000.0)

    def test_year_one_row(self) -> None:
        row = self.result.rows[1]
        self.assertEqual(row.revenue_eur, 150_000.0)
        self.assertEqual(row.opex_eur, 30_000.0)
        self.assertEqual(row.net_cash_flow_eur, 120_000.0)
        self.assertAlmostEqual(row.discount_factor, 0.925926, places=6)
        self.assertAlmostEqual(row.discounted_cash_flow_eur, 111_111.11, places=2)
        self.assertAlmostEqual(row.cumulative_cash_flow_eur, -880_000.0, places=2)
        self.assertAlmostEqual(row.cumulative_discounted_cash_flow_eur, -888_888.89, places=2)

    def test_year_four_row(self) -> None:
        row = self.result.rows[4]
        self.assertAlmostEqual(row.revenue_eur, 159_181.20, places=2)
        self.assertAlmostEqual(row.opex_eur, 31_836.24, places=2)
        self.assertAlmostEqual(row.net_cash_flow_eur, 127_344.96, places=2)
        self.assertAlmostEqual(row.discount_factor, 0.735030, places=6)
        self.assertAlmostEqual(row.discounted_cash_flow_eur, 93_602.35, places=2)

    def test_year_eight_turns_the_cumulative_flow_positive(self) -> None:
        self.assertAlmostEqual(self.result.rows[7].cumulative_cash_flow_eur, -107_885.99, places=2)
        self.assertAlmostEqual(self.result.rows[8].net_cash_flow_eur, 137_842.28, places=2)
        self.assertAlmostEqual(self.result.rows[8].cumulative_cash_flow_eur, 29_956.29, places=2)

    def test_year_ten_row(self) -> None:
        row = self.result.rows[10]
        self.assertAlmostEqual(row.revenue_eur, 179_263.89, places=2)
        self.assertAlmostEqual(row.opex_eur, 35_852.78, places=2)
        self.assertAlmostEqual(row.net_cash_flow_eur, 143_411.11, places=2)
        self.assertAlmostEqual(row.discounted_cash_flow_eur, 66_427.09, places=2)
        self.assertAlmostEqual(row.cumulative_cash_flow_eur, 313_966.52, places=2)
        self.assertAlmostEqual(row.cumulative_discounted_cash_flow_eur, -129_260.55, places=2)

    def test_npv_matches_the_last_cumulative_discounted_value(self) -> None:
        self.assertAlmostEqual(self.result.npv_eur, -129_260.55, places=2)
        self.assertAlmostEqual(
            self.result.npv_eur,
            self.result.rows[-1].cumulative_discounted_cash_flow_eur,
            places=6,
        )

    def test_irr_is_5_1310_percent(self) -> None:
        self.assertIsNotNone(self.result.irr_fraction)
        assert self.result.irr_fraction is not None
        self.assertAlmostEqual(self.result.irr_fraction, 0.051310, places=6)

    def test_simple_payback_is_7_7827_years(self) -> None:
        self.assertIsNotNone(self.result.simple_payback_years)
        assert self.result.simple_payback_years is not None
        self.assertAlmostEqual(self.result.simple_payback_years, 7.7827, places=4)

    def test_discounted_payback_never_happens(self) -> None:
        self.assertIsNone(self.result.discounted_payback_years)

    def test_the_table_has_one_row_per_year(self) -> None:
        self.assertEqual(len(self.result.rows), 11)
        self.assertEqual([row.year for row in self.result.rows], list(range(11)))
        self.assertEqual(self.result.asset_name, "Worked example")

    def test_cash_flows_property_mirrors_the_table(self) -> None:
        self.assertEqual(
            self.result.cash_flows_eur,
            tuple(row.net_cash_flow_eur for row in self.result.rows),
        )


class BuildYearRowsTests(unittest.TestCase):
    def test_multiple_streams_are_summed_per_year(self) -> None:
        asset = Asset(
            name="Two streams",
            project_life_years=2,
            capex_eur=100_000.0,
            revenues=(
                RevenueStream(name="energy", year_one_amount_eur=50_000.0),
                RevenueStream(
                    name="capacity",
                    year_one_amount_eur=10_000.0,
                    escalation_fraction_per_year=0.10,
                ),
            ),
            fixed_opex_eur=5_000.0,
            discount_rate_fraction=0.05,
        )
        rows = build_year_rows(asset)
        self.assertEqual(rows[1].revenue_eur, 60_000.0)
        self.assertEqual(rows[2].revenue_eur, 61_000.0)
        self.assertEqual(rows[2].opex_eur, 5_000.0)
        self.assertEqual(rows[2].net_cash_flow_eur, 56_000.0)


class InternalRateOfReturnTests(unittest.TestCase):
    def test_recovers_a_known_rate(self) -> None:
        # -100 today and 110 in one year is exactly 10%.
        irr = internal_rate_of_return([-100.0, 110.0])
        self.assertIsNotNone(irr)
        assert irr is not None
        self.assertAlmostEqual(irr, 0.10, places=9)

    def test_no_sign_change_returns_none(self) -> None:
        self.assertIsNone(internal_rate_of_return([-100.0, -10.0, -10.0]))

    def test_two_sign_changes_return_none(self) -> None:
        self.assertIsNone(internal_rate_of_return([-100.0, 230.0, -132.0]))

    def test_a_rate_beyond_the_search_window_returns_none(self) -> None:
        # -1 then 100 solves at 9,900%, far beyond the 1,000% ceiling.
        self.assertIsNone(internal_rate_of_return([-1.0, 100.0]))

    def test_zeros_are_ignored_when_counting_sign_changes(self) -> None:
        self.assertEqual(_sign_changes([-1.0, 0.0, 0.0, 1.0]), 1)
        irr = internal_rate_of_return([-100.0, 0.0, 121.0])
        self.assertIsNotNone(irr)
        assert irr is not None
        self.assertAlmostEqual(irr, 0.10, places=9)

    def test_too_few_or_non_finite_flows_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two cash flows"):
            internal_rate_of_return([-100.0])
        with self.assertRaisesRegex(ValueError, "cash flows must be finite"):
            internal_rate_of_return([-100.0, float("nan")])


class PaybackTests(unittest.TestCase):
    def test_interpolates_inside_the_crossing_year(self) -> None:
        # -100, then 60 and 60: crosses during year 2 at 1 + 40/60.
        payback = _payback_years([-100.0, 60.0, 60.0], None)
        self.assertIsNotNone(payback)
        assert payback is not None
        self.assertAlmostEqual(payback, 1.0 + 40.0 / 60.0, places=9)

    def test_a_non_negative_first_flow_pays_back_immediately(self) -> None:
        self.assertEqual(_payback_years([10.0, 5.0], None), 0.0)

    def test_never_recovering_returns_none(self) -> None:
        self.assertIsNone(_payback_years([-100.0, 10.0, 10.0], None))

    def test_discounting_delays_the_payback(self) -> None:
        simple = _payback_years([-100.0, 60.0, 60.0, 60.0], None)
        discounted = _payback_years([-100.0, 60.0, 60.0, 60.0], 0.10)
        assert simple is not None
        assert discounted is not None
        self.assertGreater(discounted, simple)


if __name__ == "__main__":
    unittest.main()
