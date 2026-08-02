"""Year-by-year project cash-flow table and the core investment metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from math import isfinite

from investlab.models import Asset
from investlab.rates import discount_factor, present_value

_IRR_LOWER_BOUND = -0.95
_IRR_FIRST_UPPER_BOUND = 1.0
_IRR_LAST_UPPER_BOUND = 10.0
_IRR_TOLERANCE = 1e-10
_IRR_MAX_ITERATIONS = 200
_MINIMUM_CASH_FLOW_COUNT = 2


@dataclass(frozen=True, slots=True)
class YearRow:
    """One row of the project cash-flow table.

    Year 0 carries the capex as a negative net cash flow and no revenue
    or opex. The cumulative columns make both payback definitions visible
    directly in the table.
    """

    year: int
    revenue_eur: float
    opex_eur: float
    net_cash_flow_eur: float
    discount_factor: float
    discounted_cash_flow_eur: float
    cumulative_cash_flow_eur: float
    cumulative_discounted_cash_flow_eur: float


@dataclass(frozen=True, slots=True)
class ProjectResult:
    """The full cash-flow table and every core metric derived from it.

    Later layers (reports, CSV export) read this result and never
    recompute the table.
    """

    asset_name: str
    rows: tuple[YearRow, ...]
    npv_eur: float
    irr_fraction: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None

    @property
    def cash_flows_eur(self) -> tuple[float, ...]:
        """Net cash flow per year, indexed from year 0."""

        return tuple(row.net_cash_flow_eur for row in self.rows)


def build_year_rows(asset: Asset) -> tuple[YearRow, ...]:
    """Build the cash-flow table for years 0 through the end of project life."""

    rows = [
        YearRow(
            year=0,
            revenue_eur=0.0,
            opex_eur=0.0,
            net_cash_flow_eur=-asset.capex_eur,
            discount_factor=1.0,
            discounted_cash_flow_eur=-asset.capex_eur,
            cumulative_cash_flow_eur=-asset.capex_eur,
            cumulative_discounted_cash_flow_eur=-asset.capex_eur,
        )
    ]
    cumulative = -asset.capex_eur
    cumulative_discounted = -asset.capex_eur
    for year in range(1, asset.project_life_years + 1):
        revenue = asset.revenue_in_year(year)
        opex = asset.opex_in_year(year)
        net = revenue - opex
        factor = discount_factor(asset.discount_rate_fraction, year)
        discounted = net * factor
        cumulative += net
        cumulative_discounted += discounted
        rows.append(
            YearRow(
                year=year,
                revenue_eur=revenue,
                opex_eur=opex,
                net_cash_flow_eur=net,
                discount_factor=factor,
                discounted_cash_flow_eur=discounted,
                cumulative_cash_flow_eur=cumulative,
                cumulative_discounted_cash_flow_eur=cumulative_discounted,
            )
        )
    return tuple(rows)


def _sign_changes(values: Sequence[float]) -> int:
    signs = [1 if value > 0 else -1 for value in values if value != 0]
    return sum(left != right for left, right in pairwise(signs))


def internal_rate_of_return(cash_flows_eur: Sequence[float]) -> float | None:
    """Return the unique conventional IRR, or ``None`` when it is absent or ambiguous.

    The IRR is found by bisection. A stream with anything other than
    exactly one sign change can have zero or several roots, so the
    function refuses to pick one and returns ``None``.
    """

    if len(cash_flows_eur) < _MINIMUM_CASH_FLOW_COUNT:
        raise ValueError("at least two cash flows are required")
    if any(not isfinite(value) for value in cash_flows_eur):
        raise ValueError("cash flows must be finite")
    if _sign_changes(cash_flows_eur) != 1:
        return None

    def value(rate: float) -> float:
        return present_value(rate, list(cash_flows_eur))

    lower = _IRR_LOWER_BOUND
    upper = _IRR_FIRST_UPPER_BOUND
    lower_value = value(lower)
    upper_value = value(upper)
    while lower_value * upper_value > 0 and upper < _IRR_LAST_UPPER_BOUND:
        upper = min(upper * 2, _IRR_LAST_UPPER_BOUND)
        upper_value = value(upper)
    if lower_value * upper_value > 0:
        return None

    for _ in range(_IRR_MAX_ITERATIONS):
        midpoint = (lower + upper) / 2
        midpoint_value = value(midpoint)
        if abs(midpoint_value) <= _IRR_TOLERANCE:
            return midpoint
        if lower_value * midpoint_value <= 0:
            upper = midpoint
        else:
            lower = midpoint
            lower_value = midpoint_value
    return (lower + upper) / 2


def _payback_years(cash_flows_eur: Sequence[float], discount_rate: float | None) -> float | None:
    """Return the fractional year when the cumulative flow first reaches zero."""

    cumulative = cash_flows_eur[0]
    if cumulative >= 0:
        return 0.0
    for year, cash_flow in enumerate(cash_flows_eur[1:], start=1):
        adjusted = cash_flow
        if discount_rate is not None:
            adjusted /= (1 + discount_rate) ** year
        previous = cumulative
        cumulative += adjusted
        if cumulative >= 0 and adjusted > 0:
            return (year - 1) + (-previous / adjusted)
    return None


def evaluate_project(asset: Asset) -> ProjectResult:
    """Evaluate the unlevered project: the table, NPV, IRR, and both paybacks."""

    rows = build_year_rows(asset)
    cash_flows = [row.net_cash_flow_eur for row in rows]
    return ProjectResult(
        asset_name=asset.name,
        rows=rows,
        npv_eur=present_value(asset.discount_rate_fraction, cash_flows),
        irr_fraction=internal_rate_of_return(cash_flows),
        simple_payback_years=_payback_years(cash_flows, None),
        discounted_payback_years=_payback_years(cash_flows, asset.discount_rate_fraction),
    )
