from __future__ import annotations

import unittest

from investlab.debt import Loan, evaluate_financed_project
from investlab.engine import evaluate_project
from investlab.fiscal import Fiscal, evaluate_after_tax
from investlab.models import Asset, RevenueStream
from investlab.montecarlo import (
    Distributions,
    Normal,
    Triangular,
    Uniform,
    interpolated_percentile,
    run_monte_carlo,
)


def worked_asset(year_one_revenue_eur: float = 150_000.0) -> Asset:
    """The asset from the worked example in docs/methodology.md."""

    return Asset(
        name="Worked example",
        project_life_years=10,
        capex_eur=1_000_000.0,
        revenues=(
            RevenueStream(
                name="energy sales",
                year_one_amount_eur=year_one_revenue_eur,
                escalation_fraction_per_year=0.02,
            ),
        ),
        fixed_opex_eur=30_000.0,
        opex_escalation_fraction_per_year=0.02,
        discount_rate_fraction=0.08,
    )


def degenerate_distributions() -> Distributions:
    """Uniform(1, 1) on every uncertain input: every draw is the base case."""

    return Distributions(
        capex=Uniform(1.0, 1.0),
        opex=Uniform(1.0, 1.0),
        revenue_by_name={"energy sales": Uniform(1.0, 1.0)},
    )


def revenue_only(distribution: Normal | Uniform | Triangular) -> Distributions:
    return Distributions(revenue_by_name={"energy sales": distribution})


class NormalValidationTests(unittest.TestCase):
    def test_the_default_floor_is_zero(self) -> None:
        self.assertEqual(Normal(mean_multiplier=1.0, stddev=0.1).floor, 0.0)

    def test_stddev_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "stddev must be greater than zero"):
            Normal(mean_multiplier=1.0, stddev=0.0)
        with self.assertRaisesRegex(ValueError, "stddev must be greater than zero"):
            Normal(mean_multiplier=1.0, stddev=-0.1)

    def test_the_floor_must_be_sane(self) -> None:
        with self.assertRaisesRegex(ValueError, "floor must be at least zero"):
            Normal(mean_multiplier=1.0, stddev=0.1, floor=-0.5)
        with self.assertRaisesRegex(ValueError, "floor must be below mean_multiplier"):
            Normal(mean_multiplier=1.0, stddev=0.1, floor=1.0)

    def test_every_field_must_be_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "mean_multiplier must be finite"):
            Normal(mean_multiplier=float("nan"), stddev=0.1)
        with self.assertRaisesRegex(ValueError, "stddev must be finite"):
            Normal(mean_multiplier=1.0, stddev=float("inf"))
        with self.assertRaisesRegex(ValueError, "floor must be finite"):
            Normal(mean_multiplier=1.0, stddev=0.1, floor=float("-inf"))


class UniformValidationTests(unittest.TestCase):
    def test_equal_bounds_are_a_valid_degenerate_distribution(self) -> None:
        self.assertEqual(Uniform(1.0, 1.0).low, 1.0)

    def test_bounds_must_be_ordered(self) -> None:
        with self.assertRaisesRegex(ValueError, "low must not exceed high"):
            Uniform(1.1, 0.9)

    def test_the_low_bound_must_be_at_least_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "low must be at least zero"):
            Uniform(-0.1, 1.0)

    def test_bounds_must_be_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "low must be finite"):
            Uniform(float("nan"), 1.0)
        with self.assertRaisesRegex(ValueError, "high must be finite"):
            Uniform(0.9, float("inf"))


class TriangularValidationTests(unittest.TestCase):
    def test_a_valid_triangle_is_accepted(self) -> None:
        self.assertEqual(Triangular(0.8, 1.0, 1.3).mode, 1.0)

    def test_the_mode_must_sit_between_the_bounds(self) -> None:
        with self.assertRaisesRegex(ValueError, "low <= mode <= high"):
            Triangular(0.9, 1.2, 1.1)
        with self.assertRaisesRegex(ValueError, "low <= mode <= high"):
            Triangular(0.9, 0.8, 1.1)

    def test_a_degenerate_triangle_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "low must be strictly below high"):
            Triangular(1.0, 1.0, 1.0)

    def test_the_low_bound_must_be_at_least_zero(self) -> None:
        with self.assertRaisesRegex(ValueError, "low must be at least zero"):
            Triangular(-0.1, 0.5, 1.0)

    def test_bounds_must_be_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "mode must be finite"):
            Triangular(0.9, float("nan"), 1.1)


class DistributionsValidationTests(unittest.TestCase):
    def test_at_least_one_distribution_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one distribution is required"):
            Distributions()

    def test_revenue_names_must_not_be_blank(self) -> None:
        with self.assertRaisesRegex(ValueError, "name must not be blank"):
            Distributions(revenue_by_name={"  ": Uniform(0.9, 1.1)})


class InterpolatedPercentileTests(unittest.TestCase):
    """Hand-checked values for the documented closest-ranks method."""

    def test_hand_worked_percentiles_of_five_values(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        self.assertEqual(interpolated_percentile(values, 5.0), 12.0)
        self.assertEqual(interpolated_percentile(values, 25.0), 20.0)
        self.assertEqual(interpolated_percentile(values, 50.0), 30.0)
        self.assertEqual(interpolated_percentile(values, 75.0), 40.0)
        self.assertEqual(interpolated_percentile(values, 95.0), 48.0)

    def test_the_input_order_does_not_matter(self) -> None:
        self.assertEqual(interpolated_percentile([50.0, 10.0, 40.0, 20.0, 30.0], 50.0), 30.0)

    def test_the_extremes_are_the_minimum_and_maximum(self) -> None:
        values = [3.0, 1.0, 2.0]
        self.assertEqual(interpolated_percentile(values, 0.0), 1.0)
        self.assertEqual(interpolated_percentile(values, 100.0), 3.0)

    def test_a_single_value_is_every_percentile(self) -> None:
        self.assertEqual(interpolated_percentile([7.0], 95.0), 7.0)

    def test_empty_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one value is required"):
            interpolated_percentile([], 50.0)

    def test_the_level_must_be_a_finite_percentage(self) -> None:
        with self.assertRaisesRegex(ValueError, "level must be between 0 and 100"):
            interpolated_percentile([1.0], -1.0)
        with self.assertRaisesRegex(ValueError, "level must be between 0 and 100"):
            interpolated_percentile([1.0], 100.5)
        with self.assertRaisesRegex(ValueError, "level must be finite"):
            interpolated_percentile([1.0], float("nan"))


class RunValidationTests(unittest.TestCase):
    def test_runs_bounds_are_enforced(self) -> None:
        for runs in (9, 10_001):
            with self.assertRaisesRegex(ValueError, "runs must be between 10 and 10000"):
                run_monte_carlo(worked_asset(), degenerate_distributions(), runs=runs, seed=1)

    def test_runs_must_be_an_integer(self) -> None:
        for runs in (True, 100.0):
            with self.assertRaisesRegex(ValueError, "runs must be an integer"):
                run_monte_carlo(
                    worked_asset(),
                    degenerate_distributions(),
                    runs=runs,  # type: ignore[arg-type]
                    seed=1,
                )

    def test_the_seed_is_required(self) -> None:
        with self.assertRaises(TypeError):
            run_monte_carlo(  # type: ignore[call-arg]
                worked_asset(), degenerate_distributions(), runs=10
            )

    def test_the_seed_must_be_an_integer(self) -> None:
        for seed in (False, 1.0, "7"):
            with self.assertRaisesRegex(ValueError, "seed must be an integer"):
                run_monte_carlo(
                    worked_asset(),
                    degenerate_distributions(),
                    runs=10,
                    seed=seed,  # type: ignore[arg-type]
                )

    def test_unknown_revenue_names_are_rejected(self) -> None:
        distributions = Distributions(revenue_by_name={"heat sales": Uniform(0.9, 1.1)})
        with self.assertRaisesRegex(ValueError, "unknown revenue stream names: heat sales"):
            run_monte_carlo(worked_asset(), distributions, runs=10, seed=1)


class DeterminismTests(unittest.TestCase):
    """The same seed must reproduce every number; a different seed must not."""

    def test_the_same_seed_reproduces_the_result_exactly(self) -> None:
        first = run_monte_carlo(worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=100, seed=42)
        second = run_monte_carlo(
            worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=100, seed=42
        )
        self.assertEqual(first.npv_percentiles_eur, second.npv_percentiles_eur)
        self.assertEqual(first.irr_percentiles_fraction, second.irr_percentiles_fraction)
        self.assertEqual(first.npv_values_eur, second.npv_values_eur)
        self.assertEqual(first.irr_values_fraction, second.irr_values_fraction)
        self.assertEqual(first, second)

    def test_the_same_seed_reproduces_every_distribution_kind(self) -> None:
        distributions = Distributions(
            capex=Normal(1.0, 0.1),
            opex=Triangular(0.8, 1.0, 1.3),
            revenue_by_name={"energy sales": Uniform(0.9, 1.1)},
        )
        first = run_monte_carlo(worked_asset(), distributions, runs=50, seed=7)
        second = run_monte_carlo(worked_asset(), distributions, runs=50, seed=7)
        self.assertEqual(first, second)

    def test_a_different_seed_produces_a_different_result(self) -> None:
        first = run_monte_carlo(worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=100, seed=42)
        other = run_monte_carlo(worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=100, seed=43)
        self.assertNotEqual(first.npv_values_eur, other.npv_values_eur)

    def test_the_seed_and_run_count_are_embedded_in_the_result(self) -> None:
        result = run_monte_carlo(worked_asset(), degenerate_distributions(), runs=10, seed=99)
        self.assertEqual(result.seed, 99)
        self.assertEqual(result.runs, 10)
        self.assertEqual(result.asset_name, "Worked example")
        self.assertEqual(len(result.npv_values_eur), 10)
        self.assertEqual(len(result.irr_values_fraction), 10)


class DegenerateDistributionTests(unittest.TestCase):
    """Uniform(1, 1) on everything must reproduce the deterministic base."""

    def test_every_run_reproduces_the_base_case_exactly(self) -> None:
        base = evaluate_project(worked_asset())
        result = run_monte_carlo(worked_asset(), degenerate_distributions(), runs=25, seed=7)
        self.assertEqual(result.npv_values_eur, (base.npv_eur,) * 25)
        self.assertEqual(result.irr_values_fraction, (base.irr_fraction,) * 25)

    def test_the_summary_collapses_onto_the_base_npv(self) -> None:
        base = evaluate_project(worked_asset())
        result = run_monte_carlo(worked_asset(), degenerate_distributions(), runs=25, seed=7)
        # Summing 25 identical floats and dividing rounds the mean by one
        # ulp; every per-run value is asserted exactly in the test above.
        self.assertAlmostEqual(result.npv_mean_eur, base.npv_eur, places=9)
        self.assertEqual(result.npv_stddev_eur, 0.0)
        for level in ("p5", "p25", "p50", "p75", "p95"):
            self.assertEqual(getattr(result.npv_percentiles_eur, level), base.npv_eur)
        self.assertEqual(result.irr_defined_count, 25)
        self.assertEqual(result.irr_undefined_count, 0)
        assert result.irr_percentiles_fraction is not None
        self.assertEqual(result.irr_percentiles_fraction.p50, base.irr_fraction)

    def test_a_stream_without_a_distribution_keeps_its_deterministic_value(self) -> None:
        two_streams = Asset(
            name="Two streams",
            project_life_years=10,
            capex_eur=1_000_000.0,
            revenues=(
                RevenueStream(name="energy sales", year_one_amount_eur=100_000.0),
                RevenueStream(name="capacity fees", year_one_amount_eur=50_000.0),
            ),
            fixed_opex_eur=30_000.0,
            discount_rate_fraction=0.08,
        )
        base = evaluate_project(two_streams)
        distributions = Distributions(revenue_by_name={"capacity fees": Uniform(1.0, 1.0)})
        result = run_monte_carlo(two_streams, distributions, runs=10, seed=4)
        self.assertEqual(result.npv_values_eur, (base.npv_eur,) * 10)

    def test_a_negative_base_npv_means_certain_loss(self) -> None:
        result = run_monte_carlo(worked_asset(), degenerate_distributions(), runs=10, seed=1)
        self.assertEqual(result.probability_npv_negative, 1.0)

    def test_the_loan_path_reproduces_the_equity_view(self) -> None:
        loan = Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=5)
        financed = evaluate_financed_project(worked_asset(), loan)
        result = run_monte_carlo(
            worked_asset(), degenerate_distributions(), runs=10, seed=5, loan=loan
        )
        self.assertEqual(result.npv_values_eur, (financed.equity_npv_eur,) * 10)
        self.assertEqual(result.irr_values_fraction, (financed.equity_irr_fraction,) * 10)

    def test_the_fiscal_path_reproduces_the_after_tax_equity_view(self) -> None:
        loan = Loan(principal_eur=600_000.0, rate_fraction=0.06, tenor_years=5)
        fiscal = Fiscal(tax_rate_fraction=0.25, depreciation_years=10, grant_eur=100_000.0)
        taxed = evaluate_after_tax(worked_asset(), fiscal, loan)
        result = run_monte_carlo(
            worked_asset(), degenerate_distributions(), runs=10, seed=5, loan=loan, fiscal=fiscal
        )
        self.assertEqual(result.npv_values_eur, (taxed.after_tax_equity_npv_eur,) * 10)
        self.assertEqual(result.irr_values_fraction, (taxed.after_tax_equity_irr_fraction,) * 10)


class EnvelopeTests(unittest.TestCase):
    """With only Uniform(0.9, 1.1) on revenue, every NPV must sit between
    the deterministic -10% and +10% revenue variants."""

    def test_every_npv_lies_inside_the_deterministic_envelope(self) -> None:
        low_npv = evaluate_project(worked_asset(135_000.0)).npv_eur
        high_npv = evaluate_project(worked_asset(165_000.0)).npv_eur
        result = run_monte_carlo(
            worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=500, seed=2026
        )
        self.assertLess(low_npv, high_npv)
        self.assertGreaterEqual(min(result.npv_values_eur), low_npv)
        self.assertLessEqual(max(result.npv_values_eur), high_npv)
        self.assertLess(min(result.npv_values_eur), max(result.npv_values_eur))

    def test_the_summary_statistics_stay_inside_the_envelope(self) -> None:
        low_npv = evaluate_project(worked_asset(135_000.0)).npv_eur
        high_npv = evaluate_project(worked_asset(165_000.0)).npv_eur
        result = run_monte_carlo(
            worked_asset(), revenue_only(Uniform(0.9, 1.1)), runs=500, seed=2026
        )
        self.assertGreaterEqual(result.npv_mean_eur, low_npv)
        self.assertLessEqual(result.npv_mean_eur, high_npv)
        self.assertGreater(result.npv_stddev_eur, 0.0)
        percentiles = result.npv_percentiles_eur
        self.assertLessEqual(percentiles.p5, percentiles.p25)
        self.assertLessEqual(percentiles.p25, percentiles.p50)
        self.assertLessEqual(percentiles.p50, percentiles.p75)
        self.assertLessEqual(percentiles.p75, percentiles.p95)
        self.assertGreaterEqual(percentiles.p5, low_npv)
        self.assertLessEqual(percentiles.p95, high_npv)

    def test_a_truncated_normal_never_breaks_its_floor(self) -> None:
        floor_npv = evaluate_project(worked_asset(135_000.0)).npv_eur
        result = run_monte_carlo(
            worked_asset(), revenue_only(Normal(1.0, 0.5, floor=0.9)), runs=200, seed=11
        )
        self.assertGreaterEqual(min(result.npv_values_eur), floor_npv)


class IrrCountingTests(unittest.TestCase):
    """Draws without a unique IRR are counted, never silently dropped."""

    def test_a_loss_making_asset_has_no_defined_irr_at_all(self) -> None:
        losing = Asset(
            name="Losing",
            project_life_years=5,
            capex_eur=100_000.0,
            revenues=(RevenueStream(name="sales", year_one_amount_eur=100_000.0),),
            fixed_opex_eur=150_000.0,
            discount_rate_fraction=0.05,
        )
        distributions = Distributions(revenue_by_name={"sales": Uniform(0.9, 1.1)})
        result = run_monte_carlo(losing, distributions, runs=20, seed=1)
        self.assertEqual(result.irr_defined_count, 0)
        self.assertEqual(result.irr_undefined_count, 20)
        self.assertIsNone(result.irr_percentiles_fraction)
        self.assertEqual(result.irr_values_fraction, (None,) * 20)
        self.assertEqual(result.probability_npv_negative, 1.0)

    def test_a_break_even_asset_splits_into_defined_and_undefined_draws(self) -> None:
        break_even = Asset(
            name="Break even",
            project_life_years=10,
            capex_eur=500_000.0,
            revenues=(RevenueStream(name="sales", year_one_amount_eur=100_000.0),),
            fixed_opex_eur=100_000.0,
            discount_rate_fraction=0.05,
        )
        distributions = Distributions(revenue_by_name={"sales": Uniform(0.5, 1.5)})
        result = run_monte_carlo(break_even, distributions, runs=100, seed=3)
        self.assertEqual(result.irr_defined_count, 57)
        self.assertEqual(result.irr_undefined_count, 43)
        self.assertEqual(result.irr_defined_count + result.irr_undefined_count, result.runs)
        assert result.irr_percentiles_fraction is not None
        defined = sorted(irr for irr in result.irr_values_fraction if irr is not None)
        self.assertEqual(result.irr_percentiles_fraction.p50, defined[len(defined) // 2])


if __name__ == "__main__":
    unittest.main()
