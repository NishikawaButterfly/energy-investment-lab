from __future__ import annotations

import unittest

from investlab.rates import discount_factor, present_value


class DiscountingTests(unittest.TestCase):
    def test_year_zero_is_never_discounted(self) -> None:
        self.assertEqual(discount_factor(0.08, 0), 1.0)

    def test_ten_percent_over_two_years(self) -> None:
        # 1 / 1.1^2 = 0.8264462809917354, checkable by hand.
        self.assertAlmostEqual(discount_factor(0.10, 2), 0.8264462809917354)

    def test_present_value_of_a_simple_stream(self) -> None:
        # -100 today plus 60 in each of two years at 10%:
        # -100 + 60/1.1 + 60/1.21 = 4.1322314049586715
        self.assertAlmostEqual(present_value(0.10, [-100.0, 60.0, 60.0]), 4.1322314049586715)

    def test_invalid_inputs_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            discount_factor(0.08, -1)
        with self.assertRaises(ValueError):
            discount_factor(-1.0, 1)


if __name__ == "__main__":
    unittest.main()
