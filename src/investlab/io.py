"""Bounded scenario ingestion and failure-safe artifact publication.

A scenario is a single JSON document that describes everything one run
needs: the asset, and optionally a loan, fiscal rules, an energy
profile for the levelized cost, a sensitivity spec, and a Monte Carlo
block with its mandatory seed. Loading is bounded and strict — the file
has a size cap, unknown keys and wrong types are rejected with the
offending field named, and a scenario either loads completely or not at
all; no partial objects escape.

Writing stages every artifact next to its target and publishes with
atomic replaces, and it refuses to overwrite existing results unless
explicitly forced.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from investlab.debt import Loan
from investlab.fiscal import Fiscal
from investlab.metrics import EnergyProfile
from investlab.models import Asset, RevenueStream
from investlab.montecarlo import Distribution, Distributions, Normal, Triangular, Uniform
from investlab.sensitivity import SensitivitySpec, SensitivitySpecError, SensitivityVariant

SCENARIO_SCHEMA_VERSION = 1
_MAX_SCENARIO_BYTES = 1_000_000

_ROOT_KEYS = {
    "schema_version",
    "asset",
    "loan",
    "fiscal",
    "energy",
    "sensitivity",
    "monte_carlo",
}
_ASSET_KEYS = {
    "name",
    "project_life_years",
    "capex_eur",
    "revenues",
    "fixed_opex_eur",
    "opex_escalation_fraction_per_year",
    "discount_rate_fraction",
}
_REVENUE_KEYS = {"name", "year_one_amount_eur", "escalation_fraction_per_year"}
_LOAN_KEYS = {"principal_eur", "rate_fraction", "tenor_years"}
_FISCAL_KEYS = {"tax_rate_fraction", "depreciation_years", "grant_eur"}
_ENERGY_KEYS = {"year_one_energy_mwh", "degradation_fraction_per_year"}
_SENSITIVITY_KEYS = {"variants"}
_VARIANT_KEYS = {"parameter", "mode", "value"}
_MONTE_CARLO_KEYS = {"runs", "seed", "distributions"}
_DISTRIBUTIONS_KEYS = {"capex", "opex", "revenue"}
_NORMAL_KEYS = {"kind", "mean_multiplier", "stddev", "floor"}
_UNIFORM_KEYS = {"kind", "low", "high"}
_TRIANGULAR_KEYS = {"kind", "low", "mode", "high"}
_DISTRIBUTION_KINDS = ("normal", "triangular", "uniform")


class ScenarioFileError(ValueError):
    """Raised when a scenario file is unsafe, malformed, or unsupported."""


@dataclass(frozen=True, slots=True)
class MonteCarloBlock:
    """The Monte Carlo request of a scenario: what varies, how often, which seed."""

    distributions: Distributions
    runs: int
    seed: int


@dataclass(frozen=True, slots=True)
class Scenario:
    """One fully parsed scenario document.

    The asset is always present; every other block is optional and
    ``None`` when the document does not carry it.
    """

    asset: Asset
    loan: Loan | None
    fiscal: Fiscal | None
    energy: EnergyProfile | None
    sensitivity: SensitivitySpec | None
    monte_carlo: MonteCarloBlock | None


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioFileError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_bounded_text(path: Path, maximum_bytes: int) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ScenarioFileError(f"cannot access {path}: {exc}") from exc
    if size > maximum_bytes:
        raise ScenarioFileError(f"{path.name} exceeds the {maximum_bytes}-byte limit")
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ScenarioFileError(f"cannot read {path} as UTF-8: {exc}") from exc


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioFileError(f"{path} must be a JSON object")
    return value


def _reject_unknown_keys(mapping: dict[str, Any], path: str, allowed: set[str]) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ScenarioFileError(f"unknown {path} key(s): {', '.join(unknown)}")


def _required_string(mapping: dict[str, Any], path: str, key: str) -> str:
    if key not in mapping:
        raise ScenarioFileError(f"{path}.{key} is required")
    value = mapping[key]
    if not isinstance(value, str) or not value.strip():
        raise ScenarioFileError(f"{path}.{key} must be a non-blank string")
    return value


def _number(mapping: dict[str, Any], path: str, key: str, default: float | None = None) -> float:
    if key not in mapping:
        if default is None:
            raise ScenarioFileError(f"{path}.{key} is required")
        return default
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ScenarioFileError(f"{path}.{key} must be a JSON number")
    return float(value)


def _integer(mapping: dict[str, Any], path: str, key: str) -> int:
    if key not in mapping:
        raise ScenarioFileError(f"{path}.{key} is required")
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioFileError(f"{path}.{key} must be a JSON integer")
    return value


@contextmanager
def _model_errors(path: str) -> Iterator[None]:
    """Re-raise a model's own ``ValueError`` with the scenario path prefixed."""

    try:
        yield
    except ScenarioFileError:
        raise
    except ValueError as exc:
        raise ScenarioFileError(f"{path}: {exc}") from exc


def _parse_asset(data: dict[str, Any]) -> Asset:
    _reject_unknown_keys(data, "asset", _ASSET_KEYS)
    if "revenues" not in data:
        raise ScenarioFileError("asset.revenues is required")
    revenues_value = data["revenues"]
    if not isinstance(revenues_value, list) or not revenues_value:
        raise ScenarioFileError("asset.revenues must be a non-empty JSON array")
    revenues: list[RevenueStream] = []
    for index, entry in enumerate(revenues_value):
        path = f"asset.revenues[{index}]"
        entry_map = _mapping(entry, path)
        _reject_unknown_keys(entry_map, path, _REVENUE_KEYS)
        with _model_errors(path):
            revenues.append(
                RevenueStream(
                    name=_required_string(entry_map, path, "name"),
                    year_one_amount_eur=_number(entry_map, path, "year_one_amount_eur"),
                    escalation_fraction_per_year=_number(
                        entry_map, path, "escalation_fraction_per_year", 0.0
                    ),
                )
            )
    with _model_errors("asset"):
        return Asset(
            name=_required_string(data, "asset", "name"),
            project_life_years=_integer(data, "asset", "project_life_years"),
            capex_eur=_number(data, "asset", "capex_eur"),
            revenues=tuple(revenues),
            fixed_opex_eur=_number(data, "asset", "fixed_opex_eur"),
            opex_escalation_fraction_per_year=_number(
                data, "asset", "opex_escalation_fraction_per_year", 0.0
            ),
            discount_rate_fraction=_number(data, "asset", "discount_rate_fraction", 0.0),
        )


def _parse_loan(data: dict[str, Any]) -> Loan:
    _reject_unknown_keys(data, "loan", _LOAN_KEYS)
    with _model_errors("loan"):
        return Loan(
            principal_eur=_number(data, "loan", "principal_eur"),
            rate_fraction=_number(data, "loan", "rate_fraction"),
            tenor_years=_integer(data, "loan", "tenor_years"),
        )


def _parse_fiscal(data: dict[str, Any]) -> Fiscal:
    _reject_unknown_keys(data, "fiscal", _FISCAL_KEYS)
    with _model_errors("fiscal"):
        return Fiscal(
            tax_rate_fraction=_number(data, "fiscal", "tax_rate_fraction"),
            depreciation_years=_integer(data, "fiscal", "depreciation_years"),
            grant_eur=_number(data, "fiscal", "grant_eur", 0.0),
        )


def _parse_energy(data: dict[str, Any]) -> EnergyProfile:
    _reject_unknown_keys(data, "energy", _ENERGY_KEYS)
    with _model_errors("energy"):
        return EnergyProfile(
            year_one_energy_mwh=_number(data, "energy", "year_one_energy_mwh"),
            degradation_fraction_per_year=_number(
                data, "energy", "degradation_fraction_per_year", 0.0
            ),
        )


def _parse_sensitivity(data: dict[str, Any]) -> SensitivitySpec:
    _reject_unknown_keys(data, "sensitivity", _SENSITIVITY_KEYS)
    if "variants" not in data:
        raise ScenarioFileError("sensitivity.variants is required")
    variants_value = data["variants"]
    if not isinstance(variants_value, list) or not variants_value:
        raise ScenarioFileError("sensitivity.variants must be a non-empty JSON array")
    variants: list[SensitivityVariant] = []
    for index, entry in enumerate(variants_value):
        path = f"sensitivity.variants[{index}]"
        entry_map = _mapping(entry, path)
        _reject_unknown_keys(entry_map, path, _VARIANT_KEYS)
        mode = entry_map.get("mode")
        if mode not in ("multiplier", "absolute"):
            raise ScenarioFileError(f"{path}.mode must be one of: multiplier, absolute")
        try:
            variants.append(
                SensitivityVariant(
                    parameter=_required_string(entry_map, path, "parameter"),
                    mode=mode,
                    value=_number(entry_map, path, "value"),
                )
            )
        except ScenarioFileError:
            raise
        except SensitivitySpecError as exc:
            raise ScenarioFileError(f"{path}: {exc}") from exc
    try:
        return SensitivitySpec(variants=tuple(variants))
    except SensitivitySpecError as exc:
        raise ScenarioFileError(f"sensitivity: {exc}") from exc


def _parse_distribution(value: Any, path: str) -> Distribution:
    data = _mapping(value, path)
    kind = data.get("kind")
    if kind not in _DISTRIBUTION_KINDS:
        raise ScenarioFileError(f"{path}.kind must be one of: {', '.join(_DISTRIBUTION_KINDS)}")
    with _model_errors(path):
        if kind == "normal":
            _reject_unknown_keys(data, path, _NORMAL_KEYS)
            return Normal(
                mean_multiplier=_number(data, path, "mean_multiplier"),
                stddev=_number(data, path, "stddev"),
                floor=_number(data, path, "floor", 0.0),
            )
        if kind == "uniform":
            _reject_unknown_keys(data, path, _UNIFORM_KEYS)
            return Uniform(low=_number(data, path, "low"), high=_number(data, path, "high"))
        _reject_unknown_keys(data, path, _TRIANGULAR_KEYS)
        return Triangular(
            low=_number(data, path, "low"),
            mode=_number(data, path, "mode"),
            high=_number(data, path, "high"),
        )


def _parse_monte_carlo(data: dict[str, Any]) -> MonteCarloBlock:
    _reject_unknown_keys(data, "monte_carlo", _MONTE_CARLO_KEYS)
    if "seed" not in data:
        raise ScenarioFileError(
            "monte_carlo.seed is required; an unseeded simulation cannot be reproduced"
        )
    runs = _integer(data, "monte_carlo", "runs")
    seed = _integer(data, "monte_carlo", "seed")
    if "distributions" not in data:
        raise ScenarioFileError("monte_carlo.distributions is required")
    distributions_data = _mapping(data["distributions"], "monte_carlo.distributions")
    _reject_unknown_keys(distributions_data, "monte_carlo.distributions", _DISTRIBUTIONS_KEYS)
    capex: Distribution | None = None
    if "capex" in distributions_data:
        capex = _parse_distribution(distributions_data["capex"], "monte_carlo.distributions.capex")
    opex: Distribution | None = None
    if "opex" in distributions_data:
        opex = _parse_distribution(distributions_data["opex"], "monte_carlo.distributions.opex")
    revenue_by_name: dict[str, Distribution] = {}
    if "revenue" in distributions_data:
        revenue_map = _mapping(distributions_data["revenue"], "monte_carlo.distributions.revenue")
        for name, entry in revenue_map.items():
            revenue_by_name[name] = _parse_distribution(
                entry, f"monte_carlo.distributions.revenue[{name!r}]"
            )
    with _model_errors("monte_carlo.distributions"):
        distributions = Distributions(capex=capex, opex=opex, revenue_by_name=revenue_by_name)
    return MonteCarloBlock(distributions=distributions, runs=runs, seed=seed)


def load_scenario(path: str | Path) -> Scenario:
    """Load one JSON scenario document without side effects.

    The read is bounded, duplicate keys are rejected, and every field
    error names the offending field with its full path. The optional
    blocks come back as ``None`` when absent. Rules that span two blocks
    — a loan larger than the capex, a sensitivity parameter the
    evaluation does not support — are enforced by the evaluation entry
    points, not here.
    """

    scenario_path = Path(path)
    try:
        payload = json.loads(
            _read_bounded_text(scenario_path, _MAX_SCENARIO_BYTES),
            object_pairs_hook=_unique_json_object,
        )
    except json.JSONDecodeError as exc:
        raise ScenarioFileError(f"invalid scenario JSON: {exc}") from exc
    root = _mapping(payload, "scenario")
    _reject_unknown_keys(root, "scenario", _ROOT_KEYS)
    if root.get("schema_version") != SCENARIO_SCHEMA_VERSION:
        raise ScenarioFileError(
            f"schema_version must be {SCENARIO_SCHEMA_VERSION}; "
            f"received {root.get('schema_version')!r}"
        )
    if "asset" not in root:
        raise ScenarioFileError("asset is required")
    asset = _parse_asset(_mapping(root["asset"], "asset"))
    loan = _parse_loan(_mapping(root["loan"], "loan")) if "loan" in root else None
    fiscal = _parse_fiscal(_mapping(root["fiscal"], "fiscal")) if "fiscal" in root else None
    energy = _parse_energy(_mapping(root["energy"], "energy")) if "energy" in root else None
    sensitivity = (
        _parse_sensitivity(_mapping(root["sensitivity"], "sensitivity"))
        if "sensitivity" in root
        else None
    )
    monte_carlo = (
        _parse_monte_carlo(_mapping(root["monte_carlo"], "monte_carlo"))
        if "monte_carlo" in root
        else None
    )
    return Scenario(
        asset=asset,
        loan=loan,
        fiscal=fiscal,
        energy=energy,
        sensitivity=sensitivity,
        monte_carlo=monte_carlo,
    )


def _stage_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".stage.tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        with suppress(OSError):
            temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def write_run_artifacts(
    output_directory: str | Path,
    results_json: str,
    report_markdown: str,
    *,
    force: bool = False,
) -> tuple[Path, Path]:
    """Publish ``results.json`` and ``report.md``, refusing silent overwrite.

    Both artifacts are staged next to their targets first, so a failure
    while staging publishes nothing, and each publication is an atomic
    replace. Existing results are only replaced when ``force`` is set.
    """

    output = Path(output_directory)
    results_path = output / "results.json"
    report_path = output / "report.md"
    existing = [path for path in (results_path, report_path) if path.exists()]
    if existing and not force:
        names = ", ".join(path.name for path in existing)
        raise FileExistsError(f"refusing to overwrite {names}; pass --force to replace them")

    staged: list[tuple[Path, Path]] = []
    try:
        for target, content in ((results_path, results_json), (report_path, report_markdown)):
            staged.append((target, _stage_text(target, content)))
        for target, temporary in staged:
            temporary.replace(target)
    finally:
        for _, temporary in staged:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
    return results_path, report_path
