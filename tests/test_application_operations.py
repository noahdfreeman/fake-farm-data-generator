import json
import unittest

from fake_farm_data_generator.core.application_operations import (
    normalize_application_operations,
    operation_to_processing_parameters,
)


class ApplicationOperationTests(unittest.TestCase):
    def test_blank_configuration_retains_one_operation_per_year(self):
        operations = normalize_application_operations("", [2024, 2025])
        self.assertEqual([item["year"] for item in operations], [2024, 2025])
        self.assertEqual(
            [item["operation_id"] for item in operations],
            ["APP_2024_001", "APP_2025_001"],
        )

    def test_all_expands_and_multiple_operations_share_a_year(self):
        configuration = [
            {"year": "all", "operation_id": "PRE", "product_name": "Fake Dry"},
            {
                "year": 2025,
                "operation_id": "POST",
                "operation_type": "Chemical Spraying",
                "rate_mode": "Variable Rate",
                "product_name": "Fake Spray",
                "target_rate": 15,
                "min_rate": 10,
                "max_rate": 20,
                "rate_unit": "gal/acre",
            },
        ]
        operations = normalize_application_operations(json.dumps(configuration), [2024, 2025])
        self.assertEqual(
            [(item["year"], item["operation_id"]) for item in operations],
            [(2024, "PRE"), (2025, "POST"), (2025, "PRE")],
        )
        post = next(item for item in operations if item["operation_id"] == "POST")
        parameters = operation_to_processing_parameters(post)
        self.assertEqual(parameters["OPERATION_TYPE"], 3)
        self.assertEqual(parameters["RATE_MODE"], 1)
        self.assertEqual(parameters["HEADLAND_PASSES"], 2)

    def test_legacy_application_headland_width_migrates_to_passes(self):
        row = {
            "year": 2025,
            "operation_id": "LEGACY",
            "equipment_width": 60,
            "headland_width": 120,
        }
        operation = normalize_application_operations(json.dumps([row]), [2025])[0]
        self.assertEqual(operation["headland_passes"], 2)

    def test_timezone_is_normalized_and_mapped_to_processing(self):
        rows = [
            {
                "year": 2025,
                "operation_id": "TZ_TEST",
                "timezone": " America/Indianapolis ",
            }
        ]
        operation = normalize_application_operations(json.dumps(rows), [2025])[0]
        self.assertEqual(operation["timezone"], "America/Indianapolis")
        self.assertEqual(
            operation_to_processing_parameters(operation)["TIMEZONE"],
            "America/Indianapolis",
        )

    def test_disabled_rows_are_ignored(self):
        rows = [
            {"enabled": False, "year": 2024, "operation_id": "SKIP"},
            {"year": 2024, "operation_id": "KEEP"},
        ]
        operations = normalize_application_operations(json.dumps(rows), [2024])
        self.assertEqual([item["operation_id"] for item in operations], ["KEEP"])

    def test_duplicate_operation_id_for_year_is_rejected(self):
        rows = [
            {"year": "all", "operation_id": "DUP"},
            {"year": 2025, "operation_id": "DUP"},
        ]
        with self.assertRaisesRegex(ValueError, "duplicated for year 2025"):
            normalize_application_operations(json.dumps(rows), [2024, 2025])

    def test_invalid_rate_and_operation_id_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "min_rate <= target_rate"):
            normalize_application_operations(
                json.dumps([{"year": 2025, "min_rate": 200, "target_rate": 100}]),
                [2025],
            )
        with self.assertRaisesRegex(ValueError, "operation_id"):
            normalize_application_operations(
                json.dumps([{"year": 2025, "operation_id": "../unsafe"}]), [2025]
            )

    def test_unselected_year_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not one of the selected"):
            normalize_application_operations(
                json.dumps([{"year": 2023, "operation_id": "APP"}]), [2024]
            )


if __name__ == "__main__":
    unittest.main()
