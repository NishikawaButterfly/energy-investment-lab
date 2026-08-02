from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from investlab.cli import main
from investlab.io import load_scenario
from investlab.report import evaluate_scenario, results_payload

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample-data" / "scenario.json"


def run_cli(argv: list[str]) -> tuple[int, str]:
    stream = StringIO()
    with redirect_stdout(stream):
        code = main(argv)
    return code, stream.getvalue()


class CliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def run_sample(self, output: Path, *extra: str) -> tuple[int, str]:
        return run_cli(["run", "--scenario", str(SAMPLE_PATH), "--output", str(output), *extra])


class RunCommandTests(CliTestCase):
    def test_the_sample_run_writes_the_expected_numbers(self) -> None:
        output = self.directory / "results"
        code, stdout = self.run_sample(output)
        self.assertEqual(code, 0)
        self.assertIn("results.json", stdout)
        self.assertIn("report.md", stdout)

        results: dict[str, Any] = json.loads((output / "results.json").read_text(encoding="utf-8"))
        base = results["base"]
        self.assertAlmostEqual(base["project"]["npv_eur"], 7_875_341.10, places=2)
        self.assertAlmostEqual(base["project"]["irr_fraction"], 0.1337, places=4)
        self.assertAlmostEqual(base["equity"]["npv_eur"], 8_733_000.20, places=2)
        self.assertAlmostEqual(base["after_tax"]["npv_eur"], 5_031_644.90, places=2)
        self.assertAlmostEqual(base["after_tax"]["irr_fraction"], 0.1133, places=4)
        self.assertAlmostEqual(base["after_tax"]["equity_npv_eur"], 5_889_304.01, places=2)
        self.assertAlmostEqual(base["mirr_fraction"], 0.0851, places=4)
        self.assertEqual(base["minimum_dscr"]["year"], 1)
        self.assertAlmostEqual(base["minimum_dscr"]["dscr"], 2.3725, places=4)
        self.assertAlmostEqual(base["lcoe_eur_per_mwh"], 43.74, places=2)

        sensitivity = results["sensitivity"]
        self.assertEqual(sensitivity["run_count"], 6)
        by_label = {row["label"]: row for row in sensitivity["rows"]}
        self.assertTrue(by_label["base"]["is_base"])
        self.assertAlmostEqual(by_label["base"]["npv_eur"], base["after_tax"]["npv_eur"], places=9)
        self.assertAlmostEqual(by_label["energy sales*0.8"]["npv_eur"], 1_213_080.10, places=2)
        self.assertAlmostEqual(by_label["discount_rate=0.09"]["npv_eur"], 2_349_160.74, places=2)

        monte_carlo = results["monte_carlo"]
        self.assertEqual(monte_carlo["seed"], 12)
        self.assertEqual(monte_carlo["runs"], 200)
        self.assertEqual(len(monte_carlo["npv_values_eur"]), 200)
        self.assertEqual(len(monte_carlo["irr_values_fraction"]), 200)
        self.assertAlmostEqual(monte_carlo["npv_percentiles_eur"]["p50"], 5_495_485.08, places=2)
        self.assertEqual(monte_carlo["probability_npv_negative"], 0.0)
        self.assertEqual(monte_carlo["irr_defined_count"], 200)
        self.assertEqual(monte_carlo["irr_undefined_count"], 0)

    def test_the_results_file_equals_a_direct_library_evaluation(self) -> None:
        output = self.directory / "results"
        self.run_sample(output)
        written = json.loads((output / "results.json").read_text(encoding="utf-8"))
        payload = results_payload(evaluate_scenario(load_scenario(SAMPLE_PATH)))
        self.assertEqual(written, json.loads(json.dumps(payload)))

    def test_the_report_carries_the_committee_lines(self) -> None:
        output = self.directory / "results"
        self.run_sample(output)
        report = (output / "report.md").read_text(encoding="utf-8")
        self.assertIn("# Investment committee report: Meadowlark Solar Park (20 MW)", report)
        self.assertIn("| Project NPV (after tax) | 5,031,645 EUR |", report)
        self.assertIn("| Equity IRR (after tax) | 16.39% |", report)
        self.assertIn("| Minimum DSCR | 2.37 (year 1) |", report)
        self.assertIn("| Levelized cost of energy | 43.74 EUR/MWh |", report)
        self.assertIn(
            "| energy sales\\*0.8 | 1,213,080 EUR | 8.11% | 7.41% | 10.49 | 1.78 |", report
        )
        self.assertIn(
            "The simulation ran 200 times with seed 12, varying the capex, the energy "
            "sales revenue, and the opex. The collected figures are the after-tax "
            "equity NPV and IRR.",
            report,
        )
        self.assertIn("| P50 | 5,495,485 EUR | 15.78% |", report)
        self.assertIn(
            "The after-tax project NPV is 5,031,645 EUR at the 7.00% discount rate, "
            "so the case clears its hurdle.",
            report,
        )
        self.assertIn("- Nothing in this report is investment advice.", report)

    def test_a_second_run_refuses_to_overwrite_without_force(self) -> None:
        output = self.directory / "results"
        self.run_sample(output)
        with self.assertRaises(SystemExit) as caught:
            self.run_sample(output)
        self.assertEqual(
            str(caught.exception),
            "error: refusing to overwrite results.json, report.md; pass --force to replace them",
        )
        code, _ = self.run_sample(output, "--force")
        self.assertEqual(code, 0)

    def test_the_same_scenario_reproduces_byte_identical_artifacts(self) -> None:
        first = self.directory / "first"
        second = self.directory / "second"
        self.run_sample(first)
        self.run_sample(second)
        self.assertEqual(
            (first / "results.json").read_bytes(), (second / "results.json").read_bytes()
        )
        self.assertEqual((first / "report.md").read_bytes(), (second / "report.md").read_bytes())

    def test_a_missing_scenario_file_exits_with_a_clear_error(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            run_cli(
                [
                    "run",
                    "--scenario",
                    str(self.directory / "absent.json"),
                    "--output",
                    str(self.directory / "results"),
                ]
            )
        self.assertTrue(str(caught.exception).startswith("error: cannot access"))

    def test_an_evaluation_error_exits_with_a_clear_error(self) -> None:
        data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        data["loan"]["principal_eur"] = 13_000_000
        scenario_path = self.directory / "scenario.json"
        scenario_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            run_cli(
                [
                    "run",
                    "--scenario",
                    str(scenario_path),
                    "--output",
                    str(self.directory / "results"),
                ]
            )
        self.assertEqual(
            str(caught.exception),
            "error: loan principal_eur must not exceed the asset capex_eur",
        )


class ValidateCommandTests(CliTestCase):
    def test_validate_reports_the_sample_scenario_contents(self) -> None:
        code, stdout = run_cli(["validate", "--scenario", str(SAMPLE_PATH)])
        self.assertEqual(code, 0)
        description = json.loads(stdout)
        self.assertEqual(description["status"], "valid")
        self.assertEqual(description["asset_name"], "Meadowlark Solar Park (20 MW)")
        self.assertEqual(description["project_life_years"], 25)
        self.assertEqual(description["revenue_streams"], ["energy sales"])
        self.assertTrue(description["loan"])
        self.assertTrue(description["fiscal"])
        self.assertTrue(description["energy_profile"])
        self.assertEqual(description["sensitivity_variant_count"], 5)
        self.assertEqual(description["monte_carlo"], {"runs": 200, "seed": 12})

    def test_validate_reports_absent_blocks_for_a_minimal_scenario(self) -> None:
        scenario_path = self.directory / "scenario.json"
        scenario_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "asset": {
                        "name": "Bare case",
                        "project_life_years": 1,
                        "capex_eur": 100.0,
                        "revenues": [{"name": "sales", "year_one_amount_eur": 150.0}],
                        "fixed_opex_eur": 0,
                    },
                }
            ),
            encoding="utf-8",
        )
        code, stdout = run_cli(["validate", "--scenario", str(scenario_path)])
        self.assertEqual(code, 0)
        description = json.loads(stdout)
        self.assertFalse(description["loan"])
        self.assertFalse(description["fiscal"])
        self.assertFalse(description["energy_profile"])
        self.assertEqual(description["sensitivity_variant_count"], 0)
        self.assertIsNone(description["monte_carlo"])

    def test_validate_rejects_a_malformed_scenario_with_the_field_named(self) -> None:
        scenario_path = self.directory / "scenario.json"
        scenario_path.write_text(
            '{"schema_version": 1, "asset": {"name": "x"}, "extra": 1}', encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as caught:
            run_cli(["validate", "--scenario", str(scenario_path)])
        self.assertEqual(str(caught.exception), "error: unknown scenario key(s): extra")


if __name__ == "__main__":
    unittest.main()
