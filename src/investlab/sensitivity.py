"""One-at-a-time sensitivities: rerun the existing evaluations, one change each.

A spec is an ordered, capped list of variants, each mapping exactly one
parameter to either a multiplier on the base value or an absolute
replacement. Every run goes through the existing evaluation entry
points — ``evaluate_financed_project`` without fiscal rules (which
reproduces the unlevered project exactly when the loan is ``None``) and
``evaluate_after_tax`` with them — so a sensitivity row can never
disagree with a direct evaluation.

The parameter names an evaluation supports are ``capex_eur``,
``discount_rate``, and ``opex_eur``, plus the name of every revenue
stream (varying its year-1 amount), plus ``loan_principal_eur`` and
``loan_rate`` when a loan is given and ``tax_rate`` when fiscal rules
are given.

The MIRR of every row uses the evaluated asset's discount rate as both
the finance and the reinvestment rate — the documented default rates —
so a ``discount_rate`` variant moves them too.

This module never touches files. The rows are flat dataclasses ready
for the CSV writer that a later layer will own.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from typing import Literal

from investlab.debt import Loan, evaluate_financed_project
from investlab.fiscal import Fiscal, evaluate_after_tax
from investlab.metrics import modified_internal_rate_of_return
from investlab.models import Asset

MAX_TOTAL_RUNS = 32
_ASSET_PARAMETERS = ("capex_eur", "discount_rate", "opex_eur")
_LOAN_PARAMETERS = ("loan_principal_eur", "loan_rate")
_FISCAL_PARAMETERS = ("tax_rate",)
_RESERVED_PARAMETERS = frozenset(_ASSET_PARAMETERS + _LOAN_PARAMETERS + _FISCAL_PARAMETERS)

ValueMode = Literal["multiplier", "absolute"]
_VALUE_MODES: tuple[ValueMode, ...] = ("multiplier", "absolute")


class SensitivitySpecError(ValueError):
    """Raised when a spec is malformed, unsupported, over the cap, or unevaluable."""


@dataclass(frozen=True, slots=True)
class SensitivityVariant:
    """One evaluation change: a single parameter set to a multiplier or absolute value."""

    parameter: str
    mode: ValueMode
    value: float

    def __post_init__(self) -> None:
        if not self.parameter.strip():
            raise SensitivitySpecError("variant parameter must not be blank")
        if self.mode not in _VALUE_MODES:
            raise SensitivitySpecError(f"variant mode must be one of: {', '.join(_VALUE_MODES)}")
        if not isfinite(self.value):
            raise SensitivitySpecError(f"{self.parameter} variant values must be finite")
        if self.mode == "multiplier" and self.value <= 0:
            raise SensitivitySpecError(f"{self.parameter} multipliers must be greater than zero")

    @property
    def label(self) -> str:
        """A short human-readable name: ``capex_eur*1.2`` or ``discount_rate=0.06``."""

        if self.mode == "multiplier":
            return f"{self.parameter}*{self.value:g}"
        return f"{self.parameter}={self.value:g}"


@dataclass(frozen=True, slots=True)
class SensitivitySpec:
    """An ordered list of one-at-a-time variants, capped at 32 runs with the base."""

    variants: tuple[SensitivityVariant, ...]

    def __post_init__(self) -> None:
        if not self.variants:
            raise SensitivitySpecError("the spec must define at least one variant")
        total_runs = 1 + len(self.variants)
        if total_runs > MAX_TOTAL_RUNS:
            raise SensitivitySpecError(
                f"the spec requests {total_runs} runs including the base case; "
                f"at most {MAX_TOTAL_RUNS} runs are supported"
            )
        seen: set[tuple[str, str, float]] = set()
        for variant in self.variants:
            key = (variant.parameter, variant.mode, variant.value)
            if key in seen:
                raise SensitivitySpecError(f"duplicate variant {variant.label!r}")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class SensitivityRow:
    """The metrics of one run, flat and ready for a CSV writer.

    The NPV, IRR, and paybacks are the project-level numbers of the
    evaluation that produced the row: pre-tax without fiscal rules,
    after-tax with them. The minimum DSCR is pre-tax and only present
    when the evaluation is levered.
    """

    label: str
    parameter: str | None
    mode: ValueMode | None
    value: float | None
    is_base: bool
    npv_eur: float
    irr_fraction: float | None
    mirr_fraction: float | None
    simple_payback_years: float | None
    discounted_payback_years: float | None
    minimum_dscr: float | None


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    """The base run plus one run per variant, in spec order."""

    asset_name: str
    base: SensitivityRow
    variants: tuple[SensitivityRow, ...]

    @property
    def rows(self) -> tuple[SensitivityRow, ...]:
        """Every run as one flat row, the base case first."""

        return (self.base, *self.variants)


def supported_parameters(
    asset: Asset, loan: Loan | None = None, fiscal: Fiscal | None = None
) -> tuple[str, ...]:
    """The exact parameter names this evaluation supports, in a stable order."""

    names = list(_ASSET_PARAMETERS)
    for stream in asset.revenues:
        if stream.name in _RESERVED_PARAMETERS:
            raise SensitivitySpecError(
                f"revenue stream name {stream.name!r} collides with a reserved "
                "sensitivity parameter"
            )
        names.append(stream.name)
    if loan is not None:
        names.extend(_LOAN_PARAMETERS)
    if fiscal is not None:
        names.extend(_FISCAL_PARAMETERS)
    return tuple(names)


def _resolved(base_value: float, variant: SensitivityVariant) -> float:
    if variant.mode == "multiplier":
        return base_value * variant.value
    return variant.value


def _apply_variant(
    asset: Asset, loan: Loan | None, fiscal: Fiscal | None, variant: SensitivityVariant
) -> tuple[Asset, Loan | None, Fiscal | None]:
    """Return copies of the inputs with exactly one parameter changed."""

    parameter = variant.parameter
    if parameter == "capex_eur":
        asset = replace(asset, capex_eur=_resolved(asset.capex_eur, variant))
    elif parameter == "discount_rate":
        rate = _resolved(asset.discount_rate_fraction, variant)
        asset = replace(asset, discount_rate_fraction=rate)
    elif parameter == "opex_eur":
        asset = replace(asset, fixed_opex_eur=_resolved(asset.fixed_opex_eur, variant))
    elif loan is not None and parameter == "loan_principal_eur":
        loan = replace(loan, principal_eur=_resolved(loan.principal_eur, variant))
    elif loan is not None and parameter == "loan_rate":
        loan = replace(loan, rate_fraction=_resolved(loan.rate_fraction, variant))
    elif fiscal is not None and parameter == "tax_rate":
        fiscal = replace(fiscal, tax_rate_fraction=_resolved(fiscal.tax_rate_fraction, variant))
    else:
        revenues = tuple(
            replace(stream, year_one_amount_eur=_resolved(stream.year_one_amount_eur, variant))
            if stream.name == parameter
            else stream
            for stream in asset.revenues
        )
        asset = replace(asset, revenues=revenues)
    return asset, loan, fiscal


def _run(
    label: str,
    variant: SensitivityVariant | None,
    asset: Asset,
    loan: Loan | None,
    fiscal: Fiscal | None,
) -> SensitivityRow:
    """Evaluate one input set through the existing entry points and flatten it."""

    if fiscal is None:
        financed = evaluate_financed_project(asset, loan)
        project = financed.project
        cash_flows = project.cash_flows_eur
        npv = project.npv_eur
        irr = project.irr_fraction
        simple = project.simple_payback_years
        discounted = project.discounted_payback_years
    else:
        after_tax = evaluate_after_tax(asset, fiscal, loan)
        financed = after_tax.financed
        cash_flows = after_tax.after_tax_cash_flows_eur
        npv = after_tax.after_tax_npv_eur
        irr = after_tax.after_tax_irr_fraction
        simple = after_tax.after_tax_simple_payback_years
        discounted = after_tax.after_tax_discounted_payback_years
    minimum = financed.minimum_dscr_row
    return SensitivityRow(
        label=label,
        parameter=variant.parameter if variant is not None else None,
        mode=variant.mode if variant is not None else None,
        value=variant.value if variant is not None else None,
        is_base=variant is None,
        npv_eur=npv,
        irr_fraction=irr,
        mirr_fraction=modified_internal_rate_of_return(
            cash_flows, asset.discount_rate_fraction, asset.discount_rate_fraction
        ),
        simple_payback_years=simple,
        discounted_payback_years=discounted,
        minimum_dscr=minimum.dscr if minimum is not None else None,
    )


def run_sensitivity(
    asset: Asset,
    spec: SensitivitySpec,
    loan: Loan | None = None,
    fiscal: Fiscal | None = None,
) -> SensitivityResult:
    """Evaluate the base case and every one-at-a-time variant of the spec.

    Each variant changes exactly one parameter of the asset, the loan,
    or the fiscal rules, and reruns the same evaluation the base case
    used. A variant naming a parameter the evaluation does not support,
    or producing inputs the models reject, raises
    ``SensitivitySpecError`` with the reason.
    """

    supported = supported_parameters(asset, loan, fiscal)
    for variant in spec.variants:
        if variant.parameter not in supported:
            raise SensitivitySpecError(
                f"unknown sensitivity parameter {variant.parameter!r}; "
                f"supported parameters: {', '.join(supported)}"
            )

    base = _run("base", None, asset, loan, fiscal)
    rows: list[SensitivityRow] = []
    for variant in spec.variants:
        try:
            varied_asset, varied_loan, varied_fiscal = _apply_variant(asset, loan, fiscal, variant)
            row = _run(variant.label, variant, varied_asset, varied_loan, varied_fiscal)
        except ValueError as error:
            raise SensitivitySpecError(
                f"variant {variant.label!r} produces an invalid evaluation: {error}"
            ) from error
        rows.append(row)
    return SensitivityResult(asset_name=asset.name, base=base, variants=tuple(rows))
