from __future__ import annotations

import unittest

from investlab.debt import Loan, evaluate_financed_project
from investlab.engine import evaluate_project, internal_rate_of_return
from investlab.metrics import EnergyProfile, levelized_cost, modified_internal_rate_of_return
from investlab.models import Asset, RevenueStream
from investlab.rates import compound_factor, present_value


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


def worked_profile() -> EnergyProfile:
    """The 2,000 MWh profile from the worked example in docs/methodology.md."""

    return EnergyProfile(year_one_energy_mwh=2_000.0, degradation_fraction_per_year=0.005)


class ModifiedIrrWorkedExampleTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.cash_flows = evaluate_project(worked_asset()).cash_flows_eur

    def test_the_future_value_of_the_positive_flows(self) -> None:
        future_value = sum(
            flow * compound_factor(0.04, 10 - year)
            for year, flow in enumerate(self.cash_flows)
            if flow > 0
        )
        self.assertAlmostEqual(future_value, 1_567_499.19, places=2)

    def test_mirr_at_6_percent_finance_and_4_percent_reinvestment(self) -> None:
        mirr = modified_internal_rate_of_return(self.cash_flows, 0.06, 0.04)
        self.assertIsNotNone(mirr)
        assert mirr is not None
        self.assertAlmostEqual(mirr, 0.045974, places=6)

    def test_mirr_sits_between_the_reinvestment_rate_and_the_irr(self) -> None:
        mirr = modified_internal_rate_of_return(self.cash_flows, 0.06, 0.04)
        assert mirr is not None
        self.assertGreater(mirr, 0.04)
        self.assertLess(mirr, 0.051310)

    def test_mirr_equals_irr_when_both_rates_are_the_irr(self) -> None:
        irr = internal_rate_of_return(self.cash_flows)
        self.assertIsNotNone(irr)
        assert irr is not None
        mirr = modified_internal_rate_of_return(self.cash_flows, irr, irr)
        assert mirr is not None
        self.assertAlmostEqual(mirr, irr, places=10)

    def test_mirr_works_on_equity_flows(self) -> None:
        financed = evaluate_financed_project(
            worked_asset(), Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=5)
        )
        mirr = modified_internal_rate_of_return(financed.equity_cash_flows_eur, 0.06, 0.04)
        self.assertIsNotNone(mirr)
        assert mirr is not None
        # By hand: |PV_negative| at 6% = 475,100.21 (years 0..5 are negative),
        # FV_positive at 4% = 745,732.16, so (745,732.16/475,100.21)^0.1 - 1.
        self.assertAlmostEqual(mirr, 0.046116, places=6)


class ModifiedIrrEdgeCaseTests(unittest.TestCase):
    def test_no_positive_flow_returns_none(self) -> None:
        self.assertIsNone(modified_internal_rate_of_return([-100.0, -10.0], 0.06, 0.04))

    def test_no_negative_flow_returns_none(self) -> None:
        self.assertIsNone(modified_internal_rate_of_return([100.0, 10.0], 0.06, 0.04))

    def test_zeros_alone_have_no_mirr(self) -> None:
        self.assertIsNone(modified_internal_rate_of_return([0.0, 0.0, 0.0], 0.06, 0.04))

    def test_a_single_period_round_trip_is_exact(self) -> None:
        # -100 today and 110 in one year: FV = 110, |PV| = 100, so 10%.
        mirr = modified_internal_rate_of_return([-100.0, 110.0], 0.06, 0.04)
        self.assertIsNotNone(mirr)
        assert mirr is not None
        self.assertAlmostEqual(mirr, 0.10, places=9)

    def test_too_few_or_non_finite_flows_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two cash flows"):
            modified_internal_rate_of_return([-100.0], 0.06, 0.04)
        with self.assertRaisesRegex(ValueError, "cash flows must be finite"):
            modified_internal_rate_of_return([-100.0, float("nan")], 0.06, 0.04)

    def test_finance_rate_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "finance_rate_fraction"):
            modified_internal_rate_of_return([-100.0, 110.0], -0.01, 0.04)
        with self.assertRaisesRegex(ValueError, "finance_rate_fraction"):
            modified_internal_rate_of_return([-100.0, 110.0], 1.5, 0.04)
        with self.assertRaisesRegex(ValueError, "finance_rate_fraction must be finite"):
            modified_internal_rate_of_return([-100.0, 110.0], float("nan"), 0.04)

    def test_reinvestment_rate_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "reinvestment_rate_fraction"):
            modified_internal_rate_of_return([-100.0, 110.0], 0.06, -0.01)
        with self.assertRaisesRegex(ValueError, "reinvestment_rate_fraction"):
            modified_internal_rate_of_return([-100.0, 110.0], 0.06, 1.5)
        with self.assertRaisesRegex(ValueError, "reinvestment_rate_fraction must be finite"):
            modified_internal_rate_of_return([-100.0, 110.0], 0.06, float("inf"))


class EnergyProfileTests(unittest.TestCase):
    def test_energy_degrades_from_year_one(self) -> None:
        profile = worked_profile()
        self.assertEqual(profile.energy_in_year(1), 2_000.0)
        # 2,000 * 0.995^3 = 1,970.15
        self.assertAlmostEqual(profile.energy_in_year(4), 1_970.15, places=2)
        # 2,000 * 0.995^9 = 1,911.78
        self.assertAlmostEqual(profile.energy_in_year(10), 1_911.78, places=2)

    def test_zero_degradation_keeps_the_energy_flat(self) -> None:
        flat = EnergyProfile(year_one_energy_mwh=2_000.0)
        self.assertEqual(flat.energy_in_year(7), 2_000.0)

    def test_year_before_one_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "year must be one or greater"):
            worked_profile().energy_in_year(0)

    def test_energy_must_be_positive_and_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            EnergyProfile(year_one_energy_mwh=0.0)
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            EnergyProfile(year_one_energy_mwh=-1.0)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            EnergyProfile(year_one_energy_mwh=float("nan"))
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            EnergyProfile(year_one_energy_mwh=1e13)

    def test_degradation_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "degradation_fraction_per_year"):
            EnergyProfile(year_one_energy_mwh=2_000.0, degradation_fraction_per_year=-0.01)
        with self.assertRaisesRegex(ValueError, "degradation_fraction_per_year"):
            EnergyProfile(year_one_energy_mwh=2_000.0, degradation_fraction_per_year=1.0)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            EnergyProfile(year_one_energy_mwh=2_000.0, degradation_fraction_per_year=float("nan"))


class LevelizedCostWorkedExampleTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.asset = worked_asset()
        self.profile = worked_profile()

    def test_the_present_value_of_the_costs(self) -> None:
        costs = [self.asset.capex_eur] + [self.asset.opex_in_year(year) for year in range(1, 11)]
        self.assertAlmostEqual(present_value(0.08, costs), 1_217_684.86, places=2)

    def test_the_present_value_of_the_energy(self) -> None:
        energies = [0.0] + [self.profile.energy_in_year(year) for year in range(1, 11)]
        self.assertAlmostEqual(present_value(0.08, energies), 13_163.58, places=2)

    def test_lcoe_is_92_50_eur_per_mwh(self) -> None:
        self.assertAlmostEqual(levelized_cost(self.asset, self.profile), 92.5041, places=4)

    def test_without_degradation_the_lcoe_drops_to_90_74(self) -> None:
        flat = EnergyProfile(year_one_energy_mwh=2_000.0)
        self.assertAlmostEqual(levelized_cost(self.asset, flat), 90.7355, places=4)

    def test_degradation_can_only_raise_the_levelized_cost(self) -> None:
        flat = EnergyProfile(year_one_energy_mwh=2_000.0)
        worn = EnergyProfile(year_one_energy_mwh=2_000.0, degradation_fraction_per_year=0.02)
        self.assertLess(levelized_cost(self.asset, flat), levelized_cost(self.asset, self.profile))
        self.assertLess(levelized_cost(self.asset, self.profile), levelized_cost(self.asset, worn))

    def test_revenues_never_enter_the_calculation(self) -> None:
        richer = Asset(
            name="Richer revenues",
            project_life_years=10,
            capex_eur=1_000_000.0,
            revenues=(
                RevenueStream(
                    name="energy sales",
                    year_one_amount_eur=300_000.0,
                    escalation_fraction_per_year=0.02,
                ),
            ),
            fixed_opex_eur=30_000.0,
            opex_escalation_fraction_per_year=0.02,
            discount_rate_fraction=0.08,
        )
        self.assertEqual(
            levelized_cost(richer, self.profile), levelized_cost(self.asset, self.profile)
        )


if __name__ == "__main__":
    unittest.main()
