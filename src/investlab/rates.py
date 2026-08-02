"""Discounting primitives shared by every calculation in the lab."""

from __future__ import annotations


def discount_factor(rate: float, year: int) -> float:
    """Present-value factor for a cash flow at the end of ``year``.

    Year 0 means today and is never discounted. The rate is a plain
    fraction, so 0.08 is eight percent.
    """

    if year < 0:
        raise ValueError("year must be zero or positive")
    if rate <= -1.0:
        raise ValueError("rate must be greater than -100%")
    return 1.0 / (1.0 + rate) ** year


def present_value(rate: float, cash_flows: list[float]) -> float:
    """Present value of a list of cash flows indexed from year 0."""

    return sum(flow * discount_factor(rate, year) for year, flow in enumerate(cash_flows))
