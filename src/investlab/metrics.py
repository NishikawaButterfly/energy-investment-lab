"""Standalone metrics beyond the core table: modified IRR and levelized cost.

These take their inputs explicitly — a cash-flow stream plus rates, or an
asset plus an energy profile — so they work on any stream the engine or
the debt layer produces, project and equity alike.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from investlab.models import Asset
from investlab.rates import compound_factor, present_value

_MAX_RATE_FRACTION = 1.0
_MAX_ENERGY_INPUT_MWH = 1_000_000_000_000.0
_MINIMUM_CASH_FLOW_COUNT = 2


def _require_rate(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")
    if not 0 <= value <= _MAX_RATE_FRACTION:
        raise ValueError(f"{name} must be a fraction between zero and {_MAX_RATE_FRACTION:g}")


def modified_internal_rate_of_return(
    cash_flows_eur: Sequence[float],
    finance_rate_fraction: float,
    reinvestment_rate_fraction: float,
) -> float | None:
    """Return the MIRR of the stream, or ``None`` when one side is empty.

    The negative flows are discounted to year 0 at the finance rate, the
    positive flows are compounded to the final year at the reinvestment
    rate, and for a stream of N + 1 flows indexed from year 0:

        MIRR = (FV_positive / |PV_negative|) ** (1 / N) - 1

    A stream with no negative flow has no investment side and one with
    no positive flow has no return side, so in both cases no MIRR exists
    and the function returns ``None`` rather than a number.
    """

    if len(cash_flows_eur) < _MINIMUM_CASH_FLOW_COUNT:
        raise ValueError("at least two cash flows are required")
    if any(not isfinite(value) for value in cash_flows_eur):
        raise ValueError("cash flows must be finite")
    _require_rate("finance_rate_fraction", finance_rate_fraction)
    _require_rate("reinvestment_rate_fraction", reinvestment_rate_fraction)

    negative_flows = [min(flow, 0.0) for flow in cash_flows_eur]
    positive_flows = [max(flow, 0.0) for flow in cash_flows_eur]
    if not any(negative_flows) or not any(positive_flows):
        return None

    horizon_years = len(cash_flows_eur) - 1
    present_value_of_negatives = present_value(finance_rate_fraction, negative_flows)
    future_value_of_positives = sum(
        flow * compound_factor(reinvestment_rate_fraction, horizon_years - year)
        for year, flow in enumerate(positive_flows)
    )
    ratio = future_value_of_positives / -present_value_of_negatives
    return float(ratio ** (1.0 / horizon_years)) - 1.0


@dataclass(frozen=True, slots=True)
class EnergyProfile:
    """Annual energy in MWh: a year-1 amount that degrades every following year.

    For a generator this is the energy produced; for a storage asset it
    is the energy discharged. Degradation is a plain fraction, so 0.005
    is half a percent per year.
    """

    year_one_energy_mwh: float
    degradation_fraction_per_year: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.year_one_energy_mwh):
            raise ValueError("year_one_energy_mwh must be finite")
        if self.year_one_energy_mwh <= 0:
            raise ValueError("year_one_energy_mwh must be greater than zero")
        if self.year_one_energy_mwh > _MAX_ENERGY_INPUT_MWH:
            raise ValueError(f"year_one_energy_mwh must not exceed {_MAX_ENERGY_INPUT_MWH:g}")
        if not isfinite(self.degradation_fraction_per_year):
            raise ValueError("degradation_fraction_per_year must be finite")
        if not 0 <= self.degradation_fraction_per_year < 1:
            raise ValueError(
                "degradation_fraction_per_year must be a fraction of at least zero and below one"
            )

    def energy_in_year(self, year: int) -> float:
        """Degraded energy for operating ``year``; year 1 is the base amount."""

        if year < 1:
            raise ValueError("year must be one or greater")
        return self.year_one_energy_mwh * (1 - self.degradation_fraction_per_year) ** (year - 1)


def levelized_cost(asset: Asset, energy: EnergyProfile) -> float:
    """Levelized cost in EUR per MWh: discounted costs over discounted energy.

    The numerator is the capex at year 0 plus every escalated opex year,
    discounted at the asset's discount rate; the denominator is the
    degraded energy of the same years, discounted at the same rate. With
    produced energy this is the LCOE; with discharged energy the same
    number is the LCOS. Revenues never enter the calculation.
    """

    operating_years = range(1, asset.project_life_years + 1)
    costs_eur = [asset.capex_eur] + [asset.opex_in_year(year) for year in operating_years]
    energies_mwh = [0.0] + [energy.energy_in_year(year) for year in operating_years]
    return present_value(asset.discount_rate_fraction, costs_eur) / present_value(
        asset.discount_rate_fraction, energies_mwh
    )
