"""Seeded Monte Carlo simulation over the uncertain inputs of an asset.

Uncertainty is expressed as dimensionless multipliers drawn from a small
closed set of distributions and applied to the deterministic inputs:
the capex, any revenue stream's year-1 amount (picked by name), and the
fixed opex. Every draw builds a perturbed asset, revalidated by the same
rules as any hand-written asset, and evaluates it through the existing
entry points — nothing in the simulation recomputes a cash flow.

The seed is a required argument on purpose: an unseeded simulation
cannot be reproduced, so its numbers cannot be checked, and a number
that cannot be checked does not ship.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from math import isfinite
from random import Random

from investlab.debt import Loan, evaluate_financed_project
from investlab.engine import evaluate_project
from investlab.fiscal import Fiscal, evaluate_after_tax
from investlab.models import Asset

_MIN_RUNS = 10
_MAX_RUNS = 10_000
_MAX_PERCENTILE_LEVEL = 100.0
_PERCENTILE_LEVELS = (5.0, 25.0, 50.0, 75.0, 95.0)


def _require_finite(name: str, value: float) -> None:
    if not isfinite(value):
        raise ValueError(f"{name} must be finite")


@dataclass(frozen=True, slots=True)
class Normal:
    """A normal multiplier truncated below at ``floor``.

    Draws at or below the floor are redrawn, so the result is a true
    truncated normal, never a clamped one — no probability mass piles up
    on the floor itself. The floor must sit below the mean, which keeps
    more than half of the distribution acceptable and so guarantees the
    redraw loop terminates quickly.
    """

    mean_multiplier: float
    stddev: float
    floor: float = 0.0

    def __post_init__(self) -> None:
        _require_finite("mean_multiplier", self.mean_multiplier)
        _require_finite("stddev", self.stddev)
        _require_finite("floor", self.floor)
        if self.stddev <= 0:
            raise ValueError("stddev must be greater than zero")
        if self.floor < 0:
            raise ValueError("floor must be at least zero")
        if self.floor >= self.mean_multiplier:
            raise ValueError("floor must be below mean_multiplier")

    def sample(self, rng: Random) -> float:
        """One multiplier draw from the truncated normal."""

        while True:
            value = rng.gauss(self.mean_multiplier, self.stddev)
            if value > self.floor:
                return value


@dataclass(frozen=True, slots=True)
class Uniform:
    """A uniform multiplier on ``[low, high]``.

    Equal bounds are allowed and make the distribution degenerate: every
    draw is exactly that value, so ``Uniform(1.0, 1.0)`` reproduces the
    deterministic case — the tests rely on this.
    """

    low: float
    high: float

    def __post_init__(self) -> None:
        _require_finite("low", self.low)
        _require_finite("high", self.high)
        if self.low < 0:
            raise ValueError("low must be at least zero")
        if self.low > self.high:
            raise ValueError("low must not exceed high")

    def sample(self, rng: Random) -> float:
        """One multiplier draw from the uniform distribution."""

        return rng.uniform(self.low, self.high)


@dataclass(frozen=True, slots=True)
class Triangular:
    """A triangular multiplier on ``[low, high]`` peaking at ``mode``."""

    low: float
    mode: float
    high: float

    def __post_init__(self) -> None:
        _require_finite("low", self.low)
        _require_finite("mode", self.mode)
        _require_finite("high", self.high)
        if self.low < 0:
            raise ValueError("low must be at least zero")
        if not self.low <= self.mode <= self.high:
            raise ValueError("bounds must satisfy low <= mode <= high")
        if self.low == self.high:
            raise ValueError("low must be strictly below high")

    def sample(self, rng: Random) -> float:
        """One multiplier draw from the triangular distribution."""

        return rng.triangular(self.low, self.high, self.mode)


type Distribution = Normal | Uniform | Triangular


@dataclass(frozen=True, slots=True)
class Distributions:
    """Which uncertain inputs vary, and how.

    Each field carries an optional multiplier distribution for one
    deterministic input: the capex, the fixed opex, and any revenue
    stream's year-1 amount keyed by the stream's name. A parameter
    without a distribution keeps its deterministic value. At least one
    parameter must vary — a simulation of nothing is a mistake.
    """

    capex: Distribution | None = None
    opex: Distribution | None = None
    revenue_by_name: Mapping[str, Distribution] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.capex is None and self.opex is None and not self.revenue_by_name:
            raise ValueError("at least one distribution is required")
        for name in self.revenue_by_name:
            if not name.strip():
                raise ValueError("revenue stream name must not be blank")


@dataclass(frozen=True, slots=True)
class Percentiles:
    """The 5/25/50/75/95 percentiles of one collected metric.

    Computed by linear interpolation between closest ranks — see
    ``interpolated_percentile`` for the exact method.
    """

    p5: float
    p25: float
    p50: float
    p75: float
    p95: float


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Every number a simulation produces, plus the seed that reproduces it.

    The raw per-run values are kept in run order so any summary figure
    can be recomputed and checked. IRR draws where no unique IRR exists
    are counted in ``irr_undefined_count`` and excluded from the IRR
    percentiles, which cover the defined subset only; with no defined
    IRR at all the percentiles are ``None``. ``probability_npv_negative``
    is the fraction of runs with a strictly negative NPV.
    """

    asset_name: str
    seed: int
    runs: int
    npv_mean_eur: float
    npv_stddev_eur: float
    npv_percentiles_eur: Percentiles
    probability_npv_negative: float
    irr_percentiles_fraction: Percentiles | None
    irr_defined_count: int
    irr_undefined_count: int
    npv_values_eur: tuple[float, ...]
    irr_values_fraction: tuple[float | None, ...]


def interpolated_percentile(values: Sequence[float], level: float) -> float:
    """Percentile of ``values`` by linear interpolation between closest ranks.

    The sorted values are treated as the quantiles at ranks 0 through
    n - 1, so for percentile level ``p`` the target rank is
    ``p / 100 * (n - 1)``; a fractional rank interpolates linearly
    between the two neighbouring sorted values. Level 0 is the minimum,
    100 the maximum, and 50 the conventional median. This is the
    "inclusive" method of ``statistics.quantiles`` and the default of
    common numerical libraries.
    """

    if not values:
        raise ValueError("at least one value is required")
    _require_finite("level", level)
    if not 0 <= level <= _MAX_PERCENTILE_LEVEL:
        raise ValueError(f"level must be between 0 and {_MAX_PERCENTILE_LEVEL:g}")
    ordered = sorted(values)
    rank = level / _MAX_PERCENTILE_LEVEL * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _percentiles(values: Sequence[float]) -> Percentiles:
    p5, p25, p50, p75, p95 = (
        interpolated_percentile(values, level) for level in _PERCENTILE_LEVELS
    )
    return Percentiles(p5=p5, p25=p25, p50=p50, p75=p75, p95=p95)


def _perturbed_asset(asset: Asset, distributions: Distributions, rng: Random) -> Asset:
    """One draw: the asset with every uncertain input multiplied by its sample.

    The draw order is fixed — capex first, then the revenue streams in
    the order they appear on the asset, then opex — so a seed always
    consumes the random stream the same way.
    """

    capex = asset.capex_eur
    if distributions.capex is not None:
        capex = asset.capex_eur * distributions.capex.sample(rng)
    revenues = []
    for stream in asset.revenues:
        distribution = distributions.revenue_by_name.get(stream.name)
        if distribution is None:
            revenues.append(stream)
        else:
            amount = stream.year_one_amount_eur * distribution.sample(rng)
            revenues.append(replace(stream, year_one_amount_eur=amount))
    opex = asset.fixed_opex_eur
    if distributions.opex is not None:
        opex = asset.fixed_opex_eur * distributions.opex.sample(rng)
    return replace(asset, capex_eur=capex, revenues=tuple(revenues), fixed_opex_eur=opex)


def _evaluate(
    asset: Asset, loan: Loan | None, fiscal: Fiscal | None
) -> tuple[float, float | None]:
    """NPV and IRR of one draw through the existing evaluation layers.

    With a fiscal policy the after-tax equity view is collected; with
    only a loan, the pre-tax equity view; with neither, the unlevered
    project. The equity view equals the project view whenever there is
    no loan, so the collected metric is always the investor's return.
    """

    if fiscal is not None:
        taxed = evaluate_after_tax(asset, fiscal, loan)
        return taxed.after_tax_equity_npv_eur, taxed.after_tax_equity_irr_fraction
    if loan is not None:
        financed = evaluate_financed_project(asset, loan)
        return financed.equity_npv_eur, financed.equity_irr_fraction
    project = evaluate_project(asset)
    return project.npv_eur, project.irr_fraction


# PLR0913: the simulation needs the asset, the uncertainty, the run count, the
# seed, and the two optional financing layers — six inputs, all irreducible.
def run_monte_carlo(  # noqa: PLR0913
    asset: Asset,
    distributions: Distributions,
    runs: int,
    seed: int,
    *,
    loan: Loan | None = None,
    fiscal: Fiscal | None = None,
) -> MonteCarloResult:
    """Run a seeded Monte Carlo simulation and summarize NPV and IRR.

    Every run perturbs the asset with fresh multiplier draws and
    evaluates it through the existing entry points; each perturbed asset
    passes the same validation as a hand-written one, and a draw that
    violates a rule of a lower layer (for example a drawn capex below
    the loan principal) raises rather than being silently skipped. The
    seed is required: the same seed always reproduces the same result,
    number for number.
    """

    if isinstance(runs, bool) or not isinstance(runs, int):
        raise ValueError("runs must be an integer")
    if not _MIN_RUNS <= runs <= _MAX_RUNS:
        raise ValueError(f"runs must be between {_MIN_RUNS} and {_MAX_RUNS}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    known_names = {stream.name for stream in asset.revenues}
    unknown = sorted(set(distributions.revenue_by_name) - known_names)
    if unknown:
        raise ValueError(f"unknown revenue stream names: {', '.join(unknown)}")

    # S311: the PRNG draws simulation multipliers, nothing security-sensitive,
    # and is explicitly seeded so every simulation is reproducible.
    rng = Random(seed)  # noqa: S311
    npv_values: list[float] = []
    irr_values: list[float | None] = []
    for _ in range(runs):
        npv, irr = _evaluate(_perturbed_asset(asset, distributions, rng), loan, fiscal)
        npv_values.append(npv)
        irr_values.append(irr)

    defined_irrs = [irr for irr in irr_values if irr is not None]
    return MonteCarloResult(
        asset_name=asset.name,
        seed=seed,
        runs=runs,
        npv_mean_eur=statistics.fmean(npv_values),
        npv_stddev_eur=statistics.stdev(npv_values),
        npv_percentiles_eur=_percentiles(npv_values),
        probability_npv_negative=sum(npv < 0 for npv in npv_values) / runs,
        irr_percentiles_fraction=_percentiles(defined_irrs) if defined_irrs else None,
        irr_defined_count=len(defined_irrs),
        irr_undefined_count=len(irr_values) - len(defined_irrs),
        npv_values_eur=tuple(npv_values),
        irr_values_fraction=tuple(irr_values),
    )
