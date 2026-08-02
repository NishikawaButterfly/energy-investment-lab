"""Command-line interface: one scenario file in, results and a report out."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, NoReturn

from investlab.io import Scenario, load_scenario, write_run_artifacts
from investlab.report import evaluate_scenario, render_report, results_payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="investlab",
        description="Evaluate energy asset investment scenarios from a JSON file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser(
        "validate", help="parse a scenario and report its contents without evaluating"
    )
    validate.add_argument("--scenario", type=Path, required=True)

    run = subparsers.add_parser(
        "run", help="evaluate a scenario and write results.json and report.md"
    )
    run.add_argument("--scenario", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--force", action="store_true")
    return parser


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"error: {message}")


def _describe(scenario: Scenario) -> dict[str, Any]:
    """What the scenario contains, without evaluating any of it."""

    monte_carlo: dict[str, int] | None = None
    if scenario.monte_carlo is not None:
        monte_carlo = {"runs": scenario.monte_carlo.runs, "seed": scenario.monte_carlo.seed}
    return {
        "status": "valid",
        "asset_name": scenario.asset.name,
        "project_life_years": scenario.asset.project_life_years,
        "revenue_streams": [stream.name for stream in scenario.asset.revenues],
        "loan": scenario.loan is not None,
        "fiscal": scenario.fiscal is not None,
        "energy_profile": scenario.energy is not None,
        "sensitivity_variant_count": (
            len(scenario.sensitivity.variants) if scenario.sensitivity is not None else 0
        ),
        "monte_carlo": monte_carlo,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
        if args.command == "validate":
            print(json.dumps(_describe(scenario), indent=2, sort_keys=True))
            return 0

        evaluation = evaluate_scenario(scenario)
        results_content = (
            json.dumps(results_payload(evaluation), allow_nan=False, indent=2, sort_keys=True)
            + "\n"
        )
        report_content = render_report(evaluation, source_name=args.scenario.name)
        results_path, report_path = write_run_artifacts(
            args.output, results_content, report_content, force=args.force
        )
        print(f"results: {results_path}")
        print(f"report: {report_path}")
        return 0
    except (OSError, ValueError) as exc:
        _fail(str(exc))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
