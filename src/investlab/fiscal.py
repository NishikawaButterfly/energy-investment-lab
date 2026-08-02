"""After-tax evaluation: corporate tax, straight-line depreciation, and grants.

Inflation deliberately has no knob of its own in this module: the
``Asset`` already escalates every revenue stream and the fixed opex
independently, which is exactly where nominal (inflated) cash flows are
expressed. A separate global inflation rate would duplicate that.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from investlab.debt import FinancedResult, Loan, evaluate_financed_project
from investlab.engine import _payback_years, internal_rate_of_return
from investlab.models import Asset
from investlab.rates import present_value

_MAX_DEPRECIATION_YEARS = 50


@dataclass(frozen=True, slots=True)
class Fiscal:
    """The tax rules applied to a project: rate, depreciation, and grant.

    The tax rate is a plain fraction, so 0.25 is twenty-five percent.
    Capex net of the grant is depreciated straight-line over
    ``depreciation_years``. The grant is received at year 0 and reduces
    the depreciable base; it is not taxed as income.
    """

    tax_rate_fraction: float
    depreciation_years: int
    grant_eur: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.tax_rate_fraction):
            raise ValueError("tax_rate_fraction must be finite")
        if not 0 <= self.tax_rate_fraction < 1:
            raise ValueError("tax_rate_fraction must be a fraction of at least zero, below one")
        if isinstance(self.depreciation_years, bool) or not isinstance(
            self.depreciation_years, int
        ):
            raise ValueError("depreciation_years must be an integer number of years")
        if not 1 <= self.depreciation_years <= _MAX_DEPRECIATION_YEARS:
            raise ValueError(f"depreciation_years must be between 1 and {_MAX_DEPRECIATION_YEARS}")
        if not isfinite(self.grant_eur):
            raise ValueError("grant_eur must be finite")
        if self.grant_eur < 0:
            raise ValueError("grant_eur must be greater than or equal to zero")


@dataclass(frozen=True, slots=True)
class FiscalYearRow:
    """The tax computation for one operating year.

    ``taxable_result_eur`` is the result before loss relief and can be
    negative. ``taxable_base_eur`` is the amount actually taxed after
    the loss carryforward is applied, and is never negative.
    """

    year: int
    operating_result_eur: float
    depreciation_eur: float
    interest_eur: float
    taxable_result_eur: float
    loss_used_eur: float
    taxable_base_eur: float
    tax_eur: float
    loss_carryforward_eur: float


@dataclass(frozen=True, slots=True)
class FiscalResult:
    """The after-tax view of a project on top of its financed evaluation.

    The after-tax metrics come from the same functions that produce the
    pre-tax metrics; nothing is recomputed differently. With a zero tax
    rate and no grant every after-tax number equals its pre-tax
    counterpart exactly.
    """

    financed: FinancedResult
    fiscal: Fiscal
    rows: tuple[FiscalYearRow, ...]
    after_tax_cash_flows_eur: tuple[float, ...]
    after_tax_npv_eur: float
    after_tax_irr_fraction: float | None
    after_tax_simple_payback_years: float | None
    after_tax_discounted_payback_years: float | None
    after_tax_equity_cash_flows_eur: tuple[float, ...]
    after_tax_equity_npv_eur: float
    after_tax_equity_irr_fraction: float | None


def build_fiscal_rows(
    financed: FinancedResult, fiscal: Fiscal, capex_eur: float
) -> tuple[FiscalYearRow, ...]:
    """Build the year-by-year tax table for an already financed project.

    The taxable result of a year is the operating result minus
    straight-line depreciation and minus loan interest when a loan is
    present; loan principal is not deductible. A negative taxable result
    is never refunded: it joins the loss carryforward, which offsets
    later positive results without time limit before any tax is charged.
    """

    interest_by_year = {row.year: row.interest_eur for row in financed.amortization}
    annual_depreciation = (capex_eur - fiscal.grant_eur) / fiscal.depreciation_years
    rows: list[FiscalYearRow] = []
    carryforward = 0.0
    for project_row in financed.project.rows[1:]:
        year = project_row.year
        depreciation = annual_depreciation if year <= fiscal.depreciation_years else 0.0
        interest = interest_by_year.get(year, 0.0)
        operating = project_row.net_cash_flow_eur
        taxable = operating - depreciation - interest
        if taxable < 0:
            loss_used = 0.0
            base = 0.0
            carryforward += -taxable
        else:
            loss_used = min(carryforward, taxable)
            base = taxable - loss_used
            carryforward -= loss_used
        rows.append(
            FiscalYearRow(
                year=year,
                operating_result_eur=operating,
                depreciation_eur=depreciation,
                interest_eur=interest,
                taxable_result_eur=taxable,
                loss_used_eur=loss_used,
                taxable_base_eur=base,
                tax_eur=fiscal.tax_rate_fraction * base,
                loss_carryforward_eur=carryforward,
            )
        )
    return tuple(rows)


def evaluate_after_tax(asset: Asset, fiscal: Fiscal, loan: Loan | None = None) -> FiscalResult:
    """Evaluate the project and equity after corporate tax.

    The grant is received at year 0 and each operating year pays the tax
    from its table row, on both the project and the equity view — one
    entity, one tax bill. With a zero rate and no grant the after-tax
    numbers reproduce the pre-tax numbers exactly.
    """

    if fiscal.depreciation_years > asset.project_life_years:
        raise ValueError("depreciation_years must not exceed the asset project_life_years")
    if fiscal.grant_eur >= asset.capex_eur:
        raise ValueError("grant_eur must be less than the asset capex_eur")

    financed = evaluate_financed_project(asset, loan)
    rows = build_fiscal_rows(financed, fiscal, asset.capex_eur)
    project_flows = [financed.project.rows[0].net_cash_flow_eur + fiscal.grant_eur]
    equity_flows = [financed.equity_cash_flows_eur[0] + fiscal.grant_eur]
    for row in rows:
        project_flows.append(row.operating_result_eur - row.tax_eur)
        equity_flows.append(financed.equity_cash_flows_eur[row.year] - row.tax_eur)
    return FiscalResult(
        financed=financed,
        fiscal=fiscal,
        rows=rows,
        after_tax_cash_flows_eur=tuple(project_flows),
        after_tax_npv_eur=present_value(asset.discount_rate_fraction, project_flows),
        after_tax_irr_fraction=internal_rate_of_return(project_flows),
        after_tax_simple_payback_years=_payback_years(project_flows, None),
        after_tax_discounted_payback_years=_payback_years(
            project_flows, asset.discount_rate_fraction
        ),
        after_tax_equity_cash_flows_eur=tuple(equity_flows),
        after_tax_equity_npv_eur=present_value(asset.discount_rate_fraction, equity_flows),
        after_tax_equity_irr_fraction=internal_rate_of_return(equity_flows),
    )
