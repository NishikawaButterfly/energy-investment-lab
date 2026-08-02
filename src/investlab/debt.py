"""Debt schedule, equity cash flows, and DSCR for a single annuity loan."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from investlab.engine import ProjectResult, evaluate_project, internal_rate_of_return
from investlab.models import Asset
from investlab.rates import present_value

_MAX_LOAN_RATE_FRACTION = 1.0
_MAX_TENOR_YEARS = 50


@dataclass(frozen=True, slots=True)
class Loan:
    """A single loan drawn in full at year 0 and repaid as an annuity.

    The rate is a plain fraction, so 0.06 is six percent. A zero rate
    repays the principal in equal parts.
    """

    principal_eur: float
    rate_fraction: float
    tenor_years: int

    def __post_init__(self) -> None:
        if not isfinite(self.principal_eur):
            raise ValueError("principal_eur must be finite")
        if self.principal_eur <= 0:
            raise ValueError("principal_eur must be greater than zero")
        if not isfinite(self.rate_fraction):
            raise ValueError("rate_fraction must be finite")
        if not 0 <= self.rate_fraction <= _MAX_LOAN_RATE_FRACTION:
            raise ValueError(
                f"rate_fraction must be a fraction between zero and {_MAX_LOAN_RATE_FRACTION:g}"
            )
        if isinstance(self.tenor_years, bool) or not isinstance(self.tenor_years, int):
            raise ValueError("tenor_years must be an integer number of years")
        if not 1 <= self.tenor_years <= _MAX_TENOR_YEARS:
            raise ValueError(f"tenor_years must be between 1 and {_MAX_TENOR_YEARS}")

    @property
    def annuity_payment_eur(self) -> float:
        """The constant annual debt service that repays the loan over the tenor."""

        if self.rate_fraction == 0:
            return self.principal_eur / self.tenor_years
        factor = self.rate_fraction / (1 - (1 + self.rate_fraction) ** -self.tenor_years)
        return self.principal_eur * factor


@dataclass(frozen=True, slots=True)
class AmortizationRow:
    """One year of the amortization table."""

    year: int
    opening_balance_eur: float
    interest_eur: float
    principal_eur: float
    payment_eur: float
    closing_balance_eur: float


@dataclass(frozen=True, slots=True)
class DscrRow:
    """Debt service cover for one year while the loan is outstanding.

    CFADS is the project operating cash flow of the year: revenue minus
    opex, before any debt service.
    """

    year: int
    cfads_eur: float
    debt_service_eur: float
    dscr: float


@dataclass(frozen=True, slots=True)
class FinancedResult:
    """The levered view of a project: debt schedule, equity flows, and DSCR.

    Without a loan the equity numbers equal the project numbers exactly
    and the debt tables are empty.
    """

    project: ProjectResult
    loan: Loan | None
    amortization: tuple[AmortizationRow, ...]
    dscr_rows: tuple[DscrRow, ...]
    minimum_dscr_row: DscrRow | None
    equity_cash_flows_eur: tuple[float, ...]
    equity_npv_eur: float
    equity_irr_fraction: float | None


def build_amortization(loan: Loan) -> tuple[AmortizationRow, ...]:
    """Build the year-by-year amortization table for the loan.

    Every year pays the annuity, split into interest on the opening
    balance and principal. The final payment retires the remaining
    balance exactly, absorbing sub-cent floating-point residue, so the
    closing balance ends at exactly zero.
    """

    payment = loan.annuity_payment_eur
    balance = loan.principal_eur
    rows: list[AmortizationRow] = []
    for year in range(1, loan.tenor_years + 1):
        interest = balance * loan.rate_fraction
        if year == loan.tenor_years:
            principal = balance
        else:
            principal = payment - interest
        closing = balance - principal
        rows.append(
            AmortizationRow(
                year=year,
                opening_balance_eur=balance,
                interest_eur=interest,
                principal_eur=principal,
                payment_eur=interest + principal,
                closing_balance_eur=closing,
            )
        )
        balance = closing
    return tuple(rows)


def evaluate_financed_project(asset: Asset, loan: Loan | None = None) -> FinancedResult:
    """Evaluate the project with an optional loan drawn in full at year 0.

    Equity receives the loan principal at year 0 and pays the debt
    service out of each operating year's cash flow. With ``loan`` set to
    ``None`` the result reproduces the unlevered project exactly.
    """

    project = evaluate_project(asset)
    if loan is None:
        return FinancedResult(
            project=project,
            loan=None,
            amortization=(),
            dscr_rows=(),
            minimum_dscr_row=None,
            equity_cash_flows_eur=project.cash_flows_eur,
            equity_npv_eur=project.npv_eur,
            equity_irr_fraction=project.irr_fraction,
        )

    if loan.principal_eur > asset.capex_eur:
        raise ValueError("loan principal_eur must not exceed the asset capex_eur")
    if loan.tenor_years > asset.project_life_years:
        raise ValueError("loan tenor_years must not exceed the asset project_life_years")

    amortization = build_amortization(loan)
    service_by_year = {row.year: row.payment_eur for row in amortization}
    equity_cash_flows = [project.rows[0].net_cash_flow_eur + loan.principal_eur]
    dscr_rows: list[DscrRow] = []
    for row in project.rows[1:]:
        service = service_by_year.get(row.year, 0.0)
        equity_cash_flows.append(row.net_cash_flow_eur - service)
        if service > 0:
            dscr_rows.append(
                DscrRow(
                    year=row.year,
                    cfads_eur=row.net_cash_flow_eur,
                    debt_service_eur=service,
                    dscr=row.net_cash_flow_eur / service,
                )
            )
    return FinancedResult(
        project=project,
        loan=loan,
        amortization=amortization,
        dscr_rows=tuple(dscr_rows),
        minimum_dscr_row=min(dscr_rows, key=lambda row: row.dscr),
        equity_cash_flows_eur=tuple(equity_cash_flows),
        equity_npv_eur=present_value(asset.discount_rate_fraction, equity_cash_flows),
        equity_irr_fraction=internal_rate_of_return(equity_cash_flows),
    )
