from __future__ import annotations

import re
import unittest
from dataclasses import replace

from investlab.debt import Loan, evaluate_financed_project
from investlab.engine import evaluate_project
from investlab.fiscal import Fiscal, evaluate_after_tax
from investlab.metrics import modified_internal_rate_of_return
from investlab.models import Asset, RevenueStream
from investlab.sensitivity import (
    MAX_TOTAL_RUNS,
    SensitivitySpec,
    SensitivitySpecError,
    SensitivityVariant,
    run_sensitivity,
    supported_parameters,
)


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


def multiplier(parameter: str, value: float) -> SensitivityVariant:
    return SensitivityVariant(parameter=parameter, mode="multiplier", value=value)


def absolute(parameter: str, value: float) -> SensitivityVariant:
    return SensitivityVariant(parameter=parameter, mode="absolute", value=value)


def spec_of(*variants: SensitivityVariant) -> SensitivitySpec:
    return SensitivitySpec(variants=variants)


class VariantValidationTests(unittest.TestCase):
    def test_a_blank_parameter_is_rejected(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "parameter must not be blank"):
            multiplier("  ", 1.2)

    def test_an_unknown_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "mode must be one of"):
            SensitivityVariant(parameter="capex_eur", mode="scale", value=1.2)  # type: ignore[arg-type]

    def test_non_finite_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "values must be finite"):
            multiplier("capex_eur", float("nan"))
        with self.assertRaisesRegex(SensitivitySpecError, "values must be finite"):
            absolute("capex_eur", float("inf"))

    def test_multipliers_must_be_positive(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "multipliers must be greater than zero"):
            multiplier("capex_eur", 0.0)
        with self.assertRaisesRegex(SensitivitySpecError, "multipliers must be greater than zero"):
            multiplier("capex_eur", -0.5)

    def test_an_absolute_zero_passes_spec_validation(self) -> None:
        # Whether zero is a legal value is the models' call at evaluation time.
        self.assertEqual(absolute("opex_eur", 0.0).value, 0.0)

    def test_labels_show_the_mode(self) -> None:
        self.assertEqual(multiplier("capex_eur", 1.2).label, "capex_eur*1.2")
        self.assertEqual(absolute("discount_rate", 0.06).label, "discount_rate=0.06")


class SpecValidationTests(unittest.TestCase):
    def test_an_empty_spec_is_rejected(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "at least one variant"):
            SensitivitySpec(variants=())

    def test_a_duplicate_variant_is_rejected(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, re.escape("'capex_eur*1.2'")):
            spec_of(multiplier("capex_eur", 1.2), multiplier("capex_eur", 1.2))

    def test_the_same_value_in_both_modes_is_not_a_duplicate(self) -> None:
        spec = spec_of(multiplier("discount_rate", 0.5), absolute("discount_rate", 0.5))
        self.assertEqual(len(spec.variants), 2)

    def test_the_run_cap_counts_the_base_case(self) -> None:
        largest = spec_of(
            *(multiplier("capex_eur", 1.0 + step / 100) for step in range(1, MAX_TOTAL_RUNS))
        )
        self.assertEqual(1 + len(largest.variants), MAX_TOTAL_RUNS)
        with self.assertRaisesRegex(SensitivitySpecError, "at most 32 runs are supported"):
            spec_of(
                *(
                    multiplier("capex_eur", 1.0 + step / 100)
                    for step in range(1, MAX_TOTAL_RUNS + 1)
                )
            )


class SupportedParameterTests(unittest.TestCase):
    def test_the_unlevered_asset_supports_its_streams_and_the_core_three(self) -> None:
        self.assertEqual(
            supported_parameters(worked_asset()),
            ("capex_eur", "discount_rate", "opex_eur", "energy sales"),
        )

    def test_a_loan_and_fiscal_rules_extend_the_list(self) -> None:
        self.assertEqual(
            supported_parameters(worked_asset(), worked_loan(), worked_fiscal()),
            (
                "capex_eur",
                "discount_rate",
                "opex_eur",
                "energy sales",
                "loan_principal_eur",
                "loan_rate",
                "tax_rate",
            ),
        )

    def test_an_unknown_parameter_is_rejected_with_the_exact_list(self) -> None:
        message = (
            "unknown sensitivity parameter 'nameplate_mw'; supported parameters: "
            "capex_eur, discount_rate, opex_eur, energy sales"
        )
        with self.assertRaisesRegex(SensitivitySpecError, re.escape(message)):
            run_sensitivity(worked_asset(), spec_of(multiplier("nameplate_mw", 1.2)))

    def test_loan_parameters_need_a_loan_and_tax_rate_needs_fiscal_rules(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, "'loan_rate'"):
            run_sensitivity(worked_asset(), spec_of(multiplier("loan_rate", 1.2)))
        with self.assertRaisesRegex(SensitivitySpecError, "'tax_rate'"):
            run_sensitivity(worked_asset(), spec_of(absolute("tax_rate", 0.3)), loan=worked_loan())

    def test_a_stream_name_may_not_shadow_a_reserved_parameter(self) -> None:
        shadowed = replace(
            worked_asset(),
            revenues=(RevenueStream(name="tax_rate", year_one_amount_eur=150_000.0),),
        )
        with self.assertRaisesRegex(SensitivitySpecError, "collides with a reserved"):
            run_sensitivity(shadowed, spec_of(multiplier("capex_eur", 1.2)))


class BaseRowTests(unittest.TestCase):
    def test_the_base_row_equals_the_direct_evaluation_exactly(self) -> None:
        result = run_sensitivity(worked_asset(), spec_of(multiplier("capex_eur", 1.2)))
        direct = evaluate_project(worked_asset())
        base = result.base
        self.assertEqual(base.npv_eur, direct.npv_eur)
        self.assertEqual(base.irr_fraction, direct.irr_fraction)
        self.assertEqual(base.simple_payback_years, direct.simple_payback_years)
        self.assertEqual(base.discounted_payback_years, direct.discounted_payback_years)
        self.assertEqual(
            base.mirr_fraction,
            modified_internal_rate_of_return(direct.cash_flows_eur, 0.08, 0.08),
        )
        self.assertIsNone(base.minimum_dscr)

    def test_the_base_row_is_flagged_and_carries_no_variant_fields(self) -> None:
        result = run_sensitivity(worked_asset(), spec_of(multiplier("capex_eur", 1.2)))
        self.assertTrue(result.base.is_base)
        self.assertEqual(result.base.label, "base")
        self.assertIsNone(result.base.parameter)
        self.assertIsNone(result.base.mode)
        self.assertIsNone(result.base.value)
        self.assertFalse(result.variants[0].is_base)

    def test_the_rows_are_flat_and_ordered_base_first(self) -> None:
        result = run_sensitivity(
            worked_asset(),
            spec_of(multiplier("capex_eur", 0.8), multiplier("energy sales", 1.2)),
        )
        self.assertEqual(result.asset_name, "Worked example")
        self.assertEqual(len(result.rows), 3)
        self.assertEqual(result.rows[0], result.base)
        self.assertEqual(
            [row.label for row in result.rows], ["base", "capex_eur*0.8", "energy sales*1.2"]
        )

    def test_the_levered_fiscal_base_equals_the_direct_evaluation_exactly(self) -> None:
        result = run_sensitivity(
            worked_asset(),
            spec_of(absolute("tax_rate", 0.3)),
            loan=worked_loan(),
            fiscal=worked_fiscal(),
        )
        direct = evaluate_after_tax(worked_asset(), worked_fiscal(), worked_loan())
        base = result.base
        self.assertEqual(base.npv_eur, direct.after_tax_npv_eur)
        self.assertEqual(base.irr_fraction, direct.after_tax_irr_fraction)
        self.assertEqual(base.simple_payback_years, direct.after_tax_simple_payback_years)
        self.assertEqual(base.discounted_payback_years, direct.after_tax_discounted_payback_years)
        assert direct.financed.minimum_dscr_row is not None
        self.assertEqual(base.minimum_dscr, direct.financed.minimum_dscr_row.dscr)
        self.assertEqual(
            base.mirr_fraction,
            modified_internal_rate_of_return(direct.after_tax_cash_flows_eur, 0.08, 0.08),
        )


class DirectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = run_sensitivity(
            worked_asset(),
            spec_of(
                multiplier("capex_eur", 1.2),
                absolute("discount_rate", 0.1),
                multiplier("energy sales", 1.2),
                multiplier("opex_eur", 1.2),
            ),
        )
        self.base_npv = self.result.base.npv_eur

    def test_more_capex_lowers_the_npv(self) -> None:
        self.assertLess(self.result.variants[0].npv_eur, self.base_npv)

    def test_a_higher_discount_rate_lowers_the_npv(self) -> None:
        self.assertLess(self.result.variants[1].npv_eur, self.base_npv)

    def test_more_revenue_raises_the_npv(self) -> None:
        self.assertGreater(self.result.variants[2].npv_eur, self.base_npv)

    def test_more_opex_lowers_the_npv(self) -> None:
        self.assertLess(self.result.variants[3].npv_eur, self.base_npv)


class WorkedExampleTests(unittest.TestCase):
    """Assert the exact digits published in docs/methodology.md."""

    def setUp(self) -> None:
        self.result = run_sensitivity(
            worked_asset(),
            spec_of(
                multiplier("capex_eur", 0.8),
                multiplier("capex_eur", 1.2),
                multiplier("energy sales", 0.8),
                multiplier("energy sales", 1.2),
                absolute("discount_rate", 0.06),
            ),
        )
        self.capex_down, self.capex_up, self.revenue_down, self.revenue_up, self.cheaper = (
            self.result.variants
        )

    def test_the_npv_column_matches_the_docs(self) -> None:
        self.assertAlmostEqual(self.result.base.npv_eur, -129_260.55, places=2)
        self.assertAlmostEqual(self.capex_down.npv_eur, 70_739.45, places=2)
        self.assertAlmostEqual(self.capex_up.npv_eur, -329_260.55, places=2)
        self.assertAlmostEqual(self.revenue_down.npv_eur, -346_945.42, places=2)
        self.assertAlmostEqual(self.revenue_up.npv_eur, 88_424.31, places=2)
        self.assertAlmostEqual(self.cheaper.npv_eur, -42_040.35, places=2)

    def test_20_percent_of_revenue_moves_the_npv_by_its_present_value(self) -> None:
        # PV(revenue) = 1.25 * 870,739.45 = 1,088,424.31, and 20% of it
        # is 217,684.86 — the PV of the opex column, since opex is
        # itself 20% of revenue.
        self.assertAlmostEqual(
            self.revenue_up.npv_eur - self.result.base.npv_eur, 217_684.86, places=2
        )
        self.assertAlmostEqual(
            self.result.base.npv_eur - self.revenue_down.npv_eur, 217_684.86, places=2
        )

    def test_a_capex_variant_moves_the_npv_undiscounted(self) -> None:
        self.assertAlmostEqual(
            self.capex_up.npv_eur - self.result.base.npv_eur, -200_000.00, places=6
        )

    def test_the_irr_column_matches_the_docs(self) -> None:
        assert self.capex_down.irr_fraction is not None
        assert self.revenue_down.irr_fraction is not None
        assert self.revenue_up.irr_fraction is not None
        assert self.capex_up.irr_fraction is not None
        self.assertAlmostEqual(self.capex_down.irr_fraction, 0.098601, places=6)
        self.assertAlmostEqual(self.capex_up.irr_fraction, 0.016344, places=6)
        self.assertAlmostEqual(self.revenue_down.irr_fraction, -0.002575, places=6)
        # capex*0.8 and energy sales*1.2 have proportional cash flows
        # (one stream is 1.25 times the other), hence the same IRR.
        self.assertAlmostEqual(self.revenue_up.irr_fraction, 0.098601, places=6)

    def test_the_discount_rate_variant_leaves_the_irr_untouched(self) -> None:
        self.assertEqual(self.cheaper.irr_fraction, self.result.base.irr_fraction)
        self.assertAlmostEqual(self.cheaper.npv_eur, -42_040.35, places=2)

    def test_the_mirr_uses_the_variant_discount_rate_on_both_sides(self) -> None:
        assert self.result.base.mirr_fraction is not None
        assert self.cheaper.mirr_fraction is not None
        self.assertAlmostEqual(self.result.base.mirr_fraction, 0.065154, places=6)
        self.assertAlmostEqual(self.cheaper.mirr_fraction, 0.055457, places=6)

    def test_the_payback_column_matches_the_docs(self) -> None:
        assert self.result.base.simple_payback_years is not None
        assert self.capex_down.simple_payback_years is not None
        assert self.capex_up.simple_payback_years is not None
        self.assertAlmostEqual(self.result.base.simple_payback_years, 7.7827, places=4)
        self.assertAlmostEqual(self.capex_down.simple_payback_years, 6.3184, places=4)
        self.assertAlmostEqual(self.capex_up.simple_payback_years, 9.2053, places=4)
        self.assertIsNone(self.revenue_down.simple_payback_years)
        assert self.capex_down.discounted_payback_years is not None
        self.assertAlmostEqual(self.capex_down.discounted_payback_years, 8.9387, places=4)
        self.assertIsNone(self.result.base.discounted_payback_years)


class LeveredFiscalVariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = run_sensitivity(
            worked_asset(),
            spec_of(
                multiplier("loan_rate", 1.2),
                multiplier("loan_principal_eur", 0.5),
                absolute("tax_rate", 0.3),
            ),
            loan=worked_loan(),
            fiscal=worked_fiscal(),
        )
        self.rate_up, self.principal_down, self.tax_up = self.result.variants

    def test_the_base_matches_the_docs(self) -> None:
        self.assertAlmostEqual(self.result.base.npv_eur, -72_657.23, places=2)
        assert self.result.base.minimum_dscr is not None
        self.assertAlmostEqual(self.result.base.minimum_dscr, 0.8425, places=4)
        assert self.result.base.mirr_fraction is not None
        self.assertAlmostEqual(self.result.base.mirr_fraction, 0.070947, places=6)

    def test_a_dearer_loan_shields_more_tax_but_covers_worse(self) -> None:
        # Interest is deductible, so a higher rate raises the after-tax
        # project NPV while dragging the minimum DSCR down.
        self.assertGreater(self.rate_up.npv_eur, self.result.base.npv_eur)
        assert self.rate_up.minimum_dscr is not None
        assert self.result.base.minimum_dscr is not None
        self.assertLess(self.rate_up.minimum_dscr, self.result.base.minimum_dscr)

    def test_half_the_principal_doubles_the_minimum_dscr(self) -> None:
        assert self.principal_down.minimum_dscr is not None
        assert self.result.base.minimum_dscr is not None
        self.assertAlmostEqual(
            self.principal_down.minimum_dscr, 2 * self.result.base.minimum_dscr, places=10
        )

    def test_a_higher_tax_rate_lowers_the_after_tax_npv(self) -> None:
        self.assertLess(self.tax_up.npv_eur, self.result.base.npv_eur)
        self.assertAlmostEqual(self.tax_up.npv_eur, -81_336.57, places=2)

    def test_variant_rows_match_their_direct_evaluations_exactly(self) -> None:
        direct = evaluate_after_tax(
            worked_asset(), worked_fiscal(), replace(worked_loan(), rate_fraction=0.072)
        )
        self.assertEqual(self.rate_up.npv_eur, direct.after_tax_npv_eur)
        assert direct.financed.minimum_dscr_row is not None
        self.assertEqual(self.rate_up.minimum_dscr, direct.financed.minimum_dscr_row.dscr)

    def test_a_levered_run_without_fiscal_rules_uses_the_pretax_project(self) -> None:
        result = run_sensitivity(
            worked_asset(), spec_of(multiplier("loan_rate", 1.2)), loan=worked_loan()
        )
        direct = evaluate_financed_project(worked_asset(), worked_loan())
        self.assertEqual(result.base.npv_eur, direct.project.npv_eur)
        assert direct.minimum_dscr_row is not None
        self.assertEqual(result.base.minimum_dscr, direct.minimum_dscr_row.dscr)
        # The pre-tax project NPV does not depend on the loan rate.
        self.assertEqual(result.variants[0].npv_eur, result.base.npv_eur)
        assert result.variants[0].minimum_dscr is not None
        self.assertLess(result.variants[0].minimum_dscr, direct.minimum_dscr_row.dscr)


class InvalidVariantTests(unittest.TestCase):
    def test_a_variant_breaking_a_model_rule_is_wrapped_with_its_label(self) -> None:
        message = "variant 'capex_eur=0' produces an invalid evaluation"
        with self.assertRaisesRegex(SensitivitySpecError, re.escape(message)):
            run_sensitivity(worked_asset(), spec_of(absolute("capex_eur", 0.0)))

    def test_a_variant_breaking_an_evaluation_rule_is_wrapped_too(self) -> None:
        # Halving the capex leaves the 600,000 loan above the 500,000 capex.
        message = "loan principal_eur must not exceed the asset capex_eur"
        with self.assertRaisesRegex(SensitivitySpecError, re.escape(message)):
            run_sensitivity(
                worked_asset(), spec_of(multiplier("capex_eur", 0.5)), loan=worked_loan()
            )

    def test_an_out_of_bounds_discount_rate_is_wrapped(self) -> None:
        with self.assertRaisesRegex(SensitivitySpecError, re.escape("'discount_rate=1.5'")):
            run_sensitivity(worked_asset(), spec_of(absolute("discount_rate", 1.5)))


class DegenerateMetricsTests(unittest.TestCase):
    def test_rows_report_none_where_no_metric_exists(self) -> None:
        loss_maker = Asset(
            name="Loss maker",
            project_life_years=2,
            capex_eur=100_000.0,
            revenues=(RevenueStream(name="sales", year_one_amount_eur=1_000.0),),
            fixed_opex_eur=50_000.0,
            discount_rate_fraction=0.05,
        )
        result = run_sensitivity(loss_maker, spec_of(multiplier("sales", 1.1)))
        for row in result.rows:
            self.assertIsNone(row.irr_fraction)
            self.assertIsNone(row.mirr_fraction)
            self.assertIsNone(row.simple_payback_years)
            self.assertIsNone(row.discounted_payback_years)
            self.assertIsNone(row.minimum_dscr)
            self.assertLess(row.npv_eur, 0.0)


class MultiStreamTests(unittest.TestCase):
    def test_a_stream_variant_touches_only_the_named_stream(self) -> None:
        two_streams = replace(
            worked_asset(),
            revenues=(
                RevenueStream(
                    name="ppa",
                    year_one_amount_eur=100_000.0,
                    escalation_fraction_per_year=0.02,
                ),
                RevenueStream(
                    name="merchant",
                    year_one_amount_eur=50_000.0,
                    escalation_fraction_per_year=0.02,
                ),
            ),
        )
        result = run_sensitivity(two_streams, spec_of(multiplier("ppa", 1.2)))
        varied = replace(
            two_streams,
            revenues=(
                replace(two_streams.revenues[0], year_one_amount_eur=120_000.0),
                two_streams.revenues[1],
            ),
        )
        self.assertEqual(result.variants[0].npv_eur, evaluate_project(varied).npv_eur)
        self.assertEqual(
            supported_parameters(two_streams),
            ("capex_eur", "discount_rate", "opex_eur", "ppa", "merchant"),
        )


if __name__ == "__main__":
    unittest.main()
