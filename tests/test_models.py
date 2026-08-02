from __future__ import annotations

import unittest

from investlab.models import Asset, RevenueStream


def stream(**overrides: object) -> RevenueStream:
    fields: dict[str, object] = {
        "name": "energy sales",
        "year_one_amount_eur": 150_000.0,
        "escalation_fraction_per_year": 0.02,
    }
    fields.update(overrides)
    return RevenueStream(**fields)  # type: ignore[arg-type]


def asset(**overrides: object) -> Asset:
    fields: dict[str, object] = {
        "name": "Worked example",
        "project_life_years": 10,
        "capex_eur": 1_000_000.0,
        "revenues": (stream(),),
        "fixed_opex_eur": 30_000.0,
        "opex_escalation_fraction_per_year": 0.02,
        "discount_rate_fraction": 0.08,
    }
    fields.update(overrides)
    return Asset(**fields)  # type: ignore[arg-type]


class RevenueStreamTests(unittest.TestCase):
    def test_amount_escalates_from_year_one(self) -> None:
        self.assertEqual(stream().amount_in_year(1), 150_000.0)
        # 150,000 * 1.02^3 = 159,181.20
        self.assertAlmostEqual(stream().amount_in_year(4), 159_181.20, places=2)

    def test_zero_escalation_keeps_the_amount_flat(self) -> None:
        flat = stream(escalation_fraction_per_year=0.0)
        self.assertEqual(flat.amount_in_year(7), 150_000.0)

    def test_year_before_one_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "year must be one or greater"):
            stream().amount_in_year(0)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "name must not be blank"):
            stream(name="   ")

    def test_amount_must_be_positive_and_finite(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            stream(year_one_amount_eur=0.0)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            stream(year_one_amount_eur=float("nan"))
        with self.assertRaisesRegex(ValueError, "must not exceed"):
            stream(year_one_amount_eur=1e16)

    def test_escalation_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "escalation_fraction_per_year"):
            stream(escalation_fraction_per_year=-1.0)
        with self.assertRaisesRegex(ValueError, "escalation_fraction_per_year"):
            stream(escalation_fraction_per_year=1.5)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            stream(escalation_fraction_per_year=float("inf"))


class AssetTests(unittest.TestCase):
    def test_a_valid_asset_is_accepted(self) -> None:
        built = asset()
        self.assertEqual(built.project_life_years, 10)
        self.assertEqual(built.capex_eur, 1_000_000.0)

    def test_revenue_in_year_sums_every_stream(self) -> None:
        two = asset(
            revenues=(
                stream(),
                stream(name="capacity payments", year_one_amount_eur=10_000.0),
            )
        )
        # 150,000 * 1.02 + 10,000 * 1.02 = 163,200
        self.assertAlmostEqual(two.revenue_in_year(2), 163_200.0, places=2)

    def test_opex_escalates_from_year_one(self) -> None:
        self.assertEqual(asset().opex_in_year(1), 30_000.0)
        # 30,000 * 1.02^3 = 31,836.24
        self.assertAlmostEqual(asset().opex_in_year(4), 31_836.24, places=2)
        with self.assertRaisesRegex(ValueError, "year must be one or greater"):
            asset().opex_in_year(0)

    def test_blank_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "asset name must not be blank"):
            asset(name="")

    def test_project_life_must_be_an_integer_between_1_and_50(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            asset(project_life_years=10.0)
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            asset(project_life_years=True)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            asset(project_life_years=0)
        with self.assertRaisesRegex(ValueError, "between 1 and 50"):
            asset(project_life_years=51)

    def test_capex_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "capex_eur must be greater than zero"):
            asset(capex_eur=0.0)
        with self.assertRaisesRegex(ValueError, "capex_eur must be greater than zero"):
            asset(capex_eur=-1.0)

    def test_at_least_one_revenue_stream_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one revenue stream"):
            asset(revenues=())

    def test_revenue_stream_names_must_be_unique(self) -> None:
        with self.assertRaisesRegex(ValueError, "names must be unique"):
            asset(revenues=(stream(), stream()))

    def test_opex_must_not_be_negative(self) -> None:
        with self.assertRaisesRegex(ValueError, "greater than or equal to zero"):
            asset(fixed_opex_eur=-1.0)
        with self.assertRaisesRegex(ValueError, "fixed_opex_eur must not exceed"):
            asset(fixed_opex_eur=1e16)
        self.assertEqual(asset(fixed_opex_eur=0.0).opex_in_year(5), 0.0)

    def test_opex_escalation_bounds_are_enforced(self) -> None:
        with self.assertRaisesRegex(ValueError, "opex_escalation_fraction_per_year"):
            asset(opex_escalation_fraction_per_year=2.0)

    def test_discount_rate_must_be_between_zero_and_one(self) -> None:
        with self.assertRaisesRegex(ValueError, "discount_rate_fraction"):
            asset(discount_rate_fraction=-0.01)
        with self.assertRaisesRegex(ValueError, "discount_rate_fraction"):
            asset(discount_rate_fraction=1.01)
        with self.assertRaisesRegex(ValueError, "must be finite"):
            asset(discount_rate_fraction=float("nan"))


if __name__ == "__main__":
    unittest.main()
