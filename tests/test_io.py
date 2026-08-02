from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from investlab.io import ScenarioFileError, load_scenario, write_run_artifacts
from investlab.montecarlo import Normal, Triangular, Uniform

SAMPLE_PATH = Path(__file__).resolve().parent.parent / "sample-data" / "scenario.json"


def sample_data() -> dict[str, Any]:
    """A fresh copy of the shipped sample scenario, ready to be mutated."""

    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def minimal_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "asset": {
            "name": "Bare case",
            "project_life_years": 1,
            "capex_eur": 100.0,
            "revenues": [{"name": "sales", "year_one_amount_eur": 150.0}],
            "fixed_opex_eur": 0,
        },
    }


class ScenarioFileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def write_scenario(self, data: dict[str, Any]) -> Path:
        path = self.directory / "scenario.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def assert_load_error(self, data: dict[str, Any], message: str) -> None:
        with self.assertRaisesRegex(ScenarioFileError, re.escape(message)):
            load_scenario(self.write_scenario(data))


class ScenarioRoundTripTests(ScenarioFileTestCase):
    def test_the_sample_scenario_round_trips_into_the_model_objects(self) -> None:
        scenario = load_scenario(self.write_scenario(sample_data()))

        asset = scenario.asset
        self.assertEqual(asset.name, "Meadowlark Solar Park (20 MW)")
        self.assertEqual(asset.project_life_years, 25)
        self.assertEqual(asset.capex_eur, 12_000_000.0)
        self.assertEqual(len(asset.revenues), 1)
        self.assertEqual(asset.revenues[0].name, "energy sales")
        self.assertEqual(asset.revenues[0].year_one_amount_eur, 2_000_000.0)
        self.assertEqual(asset.revenues[0].escalation_fraction_per_year, 0.01)
        self.assertEqual(asset.fixed_opex_eur, 400_000.0)
        self.assertEqual(asset.opex_escalation_fraction_per_year, 0.02)
        self.assertEqual(asset.discount_rate_fraction, 0.07)

        assert scenario.loan is not None
        self.assertEqual(scenario.loan.principal_eur, 7_000_000.0)
        self.assertEqual(scenario.loan.rate_fraction, 0.05)
        self.assertEqual(scenario.loan.tenor_years, 15)

        assert scenario.fiscal is not None
        self.assertEqual(scenario.fiscal.tax_rate_fraction, 0.25)
        self.assertEqual(scenario.fiscal.depreciation_years, 20)
        self.assertEqual(scenario.fiscal.grant_eur, 0.0)

        assert scenario.energy is not None
        self.assertEqual(scenario.energy.year_one_energy_mwh, 36_000.0)
        self.assertEqual(scenario.energy.degradation_fraction_per_year, 0.005)

        assert scenario.sensitivity is not None
        self.assertEqual(
            [variant.label for variant in scenario.sensitivity.variants],
            [
                "capex_eur*0.8",
                "capex_eur*1.2",
                "energy sales*0.8",
                "energy sales*1.2",
                "discount_rate=0.09",
            ],
        )

        assert scenario.monte_carlo is not None
        self.assertEqual(scenario.monte_carlo.runs, 200)
        self.assertEqual(scenario.monte_carlo.seed, 12)
        distributions = scenario.monte_carlo.distributions
        self.assertEqual(distributions.capex, Normal(mean_multiplier=1.0, stddev=0.05))
        self.assertEqual(distributions.opex, Uniform(low=0.95, high=1.1))
        self.assertEqual(
            distributions.revenue_by_name,
            {"energy sales": Triangular(low=0.85, mode=1.0, high=1.1)},
        )

    def test_a_minimal_scenario_loads_with_every_optional_block_absent(self) -> None:
        scenario = load_scenario(self.write_scenario(minimal_data()))
        self.assertEqual(scenario.asset.name, "Bare case")
        self.assertEqual(scenario.asset.revenues[0].escalation_fraction_per_year, 0.0)
        self.assertEqual(scenario.asset.opex_escalation_fraction_per_year, 0.0)
        self.assertEqual(scenario.asset.discount_rate_fraction, 0.0)
        self.assertIsNone(scenario.loan)
        self.assertIsNone(scenario.fiscal)
        self.assertIsNone(scenario.energy)
        self.assertIsNone(scenario.sensitivity)
        self.assertIsNone(scenario.monte_carlo)


class ScenarioErrorTests(ScenarioFileTestCase):
    def test_an_unknown_root_key_is_rejected_by_name(self) -> None:
        data = minimal_data()
        data["grants"] = {}
        self.assert_load_error(data, "unknown scenario key(s): grants")

    def test_an_unknown_asset_key_is_rejected_by_name(self) -> None:
        data = minimal_data()
        data["asset"]["capacity_mw"] = 20
        self.assert_load_error(data, "unknown asset key(s): capacity_mw")

    def test_an_unknown_loan_key_is_rejected_by_name(self) -> None:
        data = sample_data()
        data["loan"]["balloon_eur"] = 1.0
        self.assert_load_error(data, "unknown loan key(s): balloon_eur")

    def test_a_wrong_number_type_is_rejected_naming_the_field(self) -> None:
        data = minimal_data()
        data["asset"]["capex_eur"] = "twelve million"
        self.assert_load_error(data, "asset.capex_eur must be a JSON number")

    def test_a_wrong_integer_type_is_rejected_naming_the_field(self) -> None:
        data = minimal_data()
        data["asset"]["project_life_years"] = 25.0
        self.assert_load_error(data, "asset.project_life_years must be a JSON integer")

    def test_a_boolean_is_not_accepted_as_a_number(self) -> None:
        data = sample_data()
        data["loan"]["rate_fraction"] = True
        self.assert_load_error(data, "loan.rate_fraction must be a JSON number")

    def test_a_missing_required_field_is_rejected_by_name(self) -> None:
        data = minimal_data()
        del data["asset"]["capex_eur"]
        self.assert_load_error(data, "asset.capex_eur is required")

    def test_missing_revenues_are_rejected_by_name(self) -> None:
        data = minimal_data()
        del data["asset"]["revenues"]
        self.assert_load_error(data, "asset.revenues is required")

    def test_empty_revenues_are_rejected(self) -> None:
        data = minimal_data()
        data["asset"]["revenues"] = []
        self.assert_load_error(data, "asset.revenues must be a non-empty JSON array")

    def test_a_revenue_entry_error_names_its_position(self) -> None:
        data = minimal_data()
        data["asset"]["revenues"][0]["year_one_amount_eur"] = None
        self.assert_load_error(data, "asset.revenues[0].year_one_amount_eur must be a JSON number")

    def test_a_model_validation_failure_carries_the_scenario_path(self) -> None:
        data = minimal_data()
        data["asset"]["capex_eur"] = -1.0
        self.assert_load_error(data, "asset: capex_eur must be greater than zero")

    def test_the_monte_carlo_seed_is_required(self) -> None:
        data = sample_data()
        del data["monte_carlo"]["seed"]
        self.assert_load_error(
            data, "monte_carlo.seed is required; an unseeded simulation cannot be reproduced"
        )

    def test_an_unknown_distribution_kind_is_rejected(self) -> None:
        data = sample_data()
        data["monte_carlo"]["distributions"]["capex"]["kind"] = "lognormal"
        self.assert_load_error(
            data,
            "monte_carlo.distributions.capex.kind must be one of: normal, triangular, uniform",
        )

    def test_a_distribution_error_carries_its_path(self) -> None:
        data = sample_data()
        data["monte_carlo"]["distributions"]["opex"] = {"kind": "uniform", "low": 2, "high": 1}
        self.assert_load_error(data, "monte_carlo.distributions.opex: low must not exceed high")

    def test_a_variant_with_a_bad_mode_is_rejected(self) -> None:
        data = sample_data()
        data["sensitivity"]["variants"][0]["mode"] = "scaled"
        self.assert_load_error(
            data, "sensitivity.variants[0].mode must be one of: multiplier, absolute"
        )

    def test_a_duplicate_variant_carries_the_sensitivity_path(self) -> None:
        data = sample_data()
        data["sensitivity"]["variants"][1] = data["sensitivity"]["variants"][0]
        self.assert_load_error(data, "sensitivity: duplicate variant 'capex_eur*0.8'")

    def test_a_missing_asset_block_is_rejected(self) -> None:
        self.assert_load_error({"schema_version": 1}, "asset is required")

    def test_a_missing_asset_name_is_rejected_by_name(self) -> None:
        data = minimal_data()
        del data["asset"]["name"]
        self.assert_load_error(data, "asset.name is required")

    def test_a_blank_asset_name_is_rejected(self) -> None:
        data = minimal_data()
        data["asset"]["name"] = "   "
        self.assert_load_error(data, "asset.name must be a non-blank string")

    def test_a_missing_integer_field_is_rejected_by_name(self) -> None:
        data = sample_data()
        del data["loan"]["tenor_years"]
        self.assert_load_error(data, "loan.tenor_years is required")

    def test_missing_sensitivity_variants_are_rejected_by_name(self) -> None:
        data = sample_data()
        data["sensitivity"] = {}
        self.assert_load_error(data, "sensitivity.variants is required")

    def test_empty_sensitivity_variants_are_rejected(self) -> None:
        data = sample_data()
        data["sensitivity"]["variants"] = []
        self.assert_load_error(data, "sensitivity.variants must be a non-empty JSON array")

    def test_a_variant_without_a_value_is_rejected_by_name(self) -> None:
        data = sample_data()
        del data["sensitivity"]["variants"][0]["value"]
        self.assert_load_error(data, "sensitivity.variants[0].value is required")

    def test_a_variant_spec_error_carries_its_position(self) -> None:
        data = sample_data()
        data["sensitivity"]["variants"][0]["value"] = -1.0
        self.assert_load_error(
            data, "sensitivity.variants[0]: capex_eur multipliers must be greater than zero"
        )

    def test_missing_monte_carlo_distributions_are_rejected_by_name(self) -> None:
        data = sample_data()
        del data["monte_carlo"]["distributions"]
        self.assert_load_error(data, "monte_carlo.distributions is required")

    def test_a_single_distribution_is_enough(self) -> None:
        data = sample_data()
        data["monte_carlo"]["distributions"] = {"opex": {"kind": "uniform", "low": 1, "high": 1}}
        scenario = load_scenario(self.write_scenario(data))
        assert scenario.monte_carlo is not None
        distributions = scenario.monte_carlo.distributions
        self.assertIsNone(distributions.capex)
        self.assertEqual(distributions.opex, Uniform(low=1.0, high=1.0))
        self.assertEqual(distributions.revenue_by_name, {})

    def test_the_schema_version_must_match(self) -> None:
        data = minimal_data()
        data["schema_version"] = 2
        self.assert_load_error(data, "schema_version must be 1; received 2")

    def test_a_non_object_document_is_rejected(self) -> None:
        path = self.directory / "scenario.json"
        path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ScenarioFileError, "scenario must be a JSON object"):
            load_scenario(path)

    def test_invalid_json_is_rejected(self) -> None:
        path = self.directory / "scenario.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(ScenarioFileError, "invalid scenario JSON"):
            load_scenario(path)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        path = self.directory / "scenario.json"
        path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
        with self.assertRaisesRegex(ScenarioFileError, "duplicate JSON key: schema_version"):
            load_scenario(path)

    def test_an_oversized_scenario_file_is_rejected(self) -> None:
        path = self.directory / "scenario.json"
        path.write_text(" " * 1_000_001, encoding="utf-8")
        with self.assertRaisesRegex(ScenarioFileError, "exceeds the 1000000-byte limit"):
            load_scenario(path)

    def test_a_missing_file_is_reported_cleanly(self) -> None:
        with self.assertRaisesRegex(ScenarioFileError, "cannot access"):
            load_scenario(self.directory / "absent.json")

    def test_a_file_that_is_not_utf8_is_reported_cleanly(self) -> None:
        path = self.directory / "scenario.json"
        path.write_bytes(b'{"schema_version": \xff\xfe}')
        with self.assertRaisesRegex(ScenarioFileError, "as UTF-8"):
            load_scenario(path)


class ArtifactWritingTests(ScenarioFileTestCase):
    def test_artifacts_are_written_and_read_back_exactly(self) -> None:
        output = self.directory / "nested" / "results"
        results_path, report_path = write_run_artifacts(output, '{"a": 1}\n', "# Report\n")
        self.assertEqual(results_path.read_text(encoding="utf-8"), '{"a": 1}\n')
        self.assertEqual(report_path.read_text(encoding="utf-8"), "# Report\n")

    def test_existing_artifacts_are_not_overwritten_without_force(self) -> None:
        output = self.directory / "results"
        write_run_artifacts(output, "first", "first report")
        with self.assertRaisesRegex(
            FileExistsError, "refusing to overwrite results.json, report.md"
        ):
            write_run_artifacts(output, "second", "second report")
        self.assertEqual((output / "results.json").read_text(encoding="utf-8"), "first")

    def test_force_replaces_existing_artifacts(self) -> None:
        output = self.directory / "results"
        write_run_artifacts(output, "first", "first report")
        write_run_artifacts(output, "second", "second report", force=True)
        self.assertEqual((output / "results.json").read_text(encoding="utf-8"), "second")
        self.assertEqual((output / "report.md").read_text(encoding="utf-8"), "second report")

    def test_no_staging_leftovers_remain_after_publication(self) -> None:
        output = self.directory / "results"
        write_run_artifacts(output, "content", "report")
        self.assertEqual(
            sorted(path.name for path in output.iterdir()), ["report.md", "results.json"]
        )


if __name__ == "__main__":
    unittest.main()
