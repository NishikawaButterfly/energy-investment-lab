"""Frozen input models that describe an energy asset's investment case."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

_MAX_PROJECT_LIFE_YEARS = 50
_MAX_MONETARY_INPUT_EUR = 1_000_000_000_000_000.0
_MAX_ESCALATION_FRACTION = 1.0
_MAX_DISCOUNT_RATE_FRACTION = 1.0


def _require_finite(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


def _require_positive_money(name: str, value: float) -> None:
    _require_finite(name, value)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    if value > _MAX_MONETARY_INPUT_EUR:
        raise ValueError(f"{name} must not exceed {_MAX_MONETARY_INPUT_EUR:g}")


def _require_nonnegative_money(name: str, value: float) -> None:
    _require_finite(name, value)
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")
    if value > _MAX_MONETARY_INPUT_EUR:
        raise ValueError(f"{name} must not exceed {_MAX_MONETARY_INPUT_EUR:g}")


def _require_escalation(name: str, value: float) -> None:
    _require_finite(name, value)
    if not -_MAX_ESCALATION_FRACTION < value <= _MAX_ESCALATION_FRACTION:
        raise ValueError(
            f"{name} must be a fraction greater than -1 and at most {_MAX_ESCALATION_FRACTION:g}"
        )


@dataclass(frozen=True, slots=True)
class RevenueStream:
    """One revenue line: a year-1 amount that escalates every following year."""

    name: str
    year_one_amount_eur: float
    escalation_fraction_per_year: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("revenue stream name must not be blank")
        _require_positive_money("year_one_amount_eur", self.year_one_amount_eur)
        _require_escalation("escalation_fraction_per_year", self.escalation_fraction_per_year)

    def amount_in_year(self, year: int) -> float:
        """Escalated amount for operating ``year``; year 1 is the base amount."""

        if year < 1:
            raise ValueError("year must be one or greater")
        return self.year_one_amount_eur * (1 + self.escalation_fraction_per_year) ** (year - 1)


@dataclass(frozen=True, slots=True)
class Asset:
    """An energy asset described by its capex, revenues, opex, and discount rate.

    Capex is spent at year 0. Every operating year from 1 to
    ``project_life_years`` earns the escalated revenues and pays the
    escalated fixed opex. All rates are plain fractions, so 0.08 is
    eight percent.
    """

    name: str
    project_life_years: int
    capex_eur: float
    revenues: tuple[RevenueStream, ...]
    fixed_opex_eur: float
    opex_escalation_fraction_per_year: float = 0.0
    discount_rate_fraction: float = 0.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("asset name must not be blank")
        if isinstance(self.project_life_years, bool) or not isinstance(
            self.project_life_years, int
        ):
            raise ValueError("project_life_years must be an integer number of years")
        if not 1 <= self.project_life_years <= _MAX_PROJECT_LIFE_YEARS:
            raise ValueError(f"project_life_years must be between 1 and {_MAX_PROJECT_LIFE_YEARS}")
        _require_positive_money("capex_eur", self.capex_eur)
        if not self.revenues:
            raise ValueError("at least one revenue stream is required")
        names = [stream.name for stream in self.revenues]
        if len(set(names)) != len(names):
            raise ValueError("revenue stream names must be unique")
        _require_nonnegative_money("fixed_opex_eur", self.fixed_opex_eur)
        _require_escalation(
            "opex_escalation_fraction_per_year", self.opex_escalation_fraction_per_year
        )
        _require_finite("discount_rate_fraction", self.discount_rate_fraction)
        if not 0 <= self.discount_rate_fraction <= _MAX_DISCOUNT_RATE_FRACTION:
            raise ValueError(
                "discount_rate_fraction must be a fraction between zero and "
                f"{_MAX_DISCOUNT_RATE_FRACTION:g}"
            )

    def revenue_in_year(self, year: int) -> float:
        """Total escalated revenue across every stream for operating ``year``."""

        return sum(stream.amount_in_year(year) for stream in self.revenues)

    def opex_in_year(self, year: int) -> float:
        """Escalated fixed opex for operating ``year``; year 1 is the base amount."""

        if year < 1:
            raise ValueError("year must be one or greater")
        return self.fixed_opex_eur * (1 + self.opex_escalation_fraction_per_year) ** (year - 1)
