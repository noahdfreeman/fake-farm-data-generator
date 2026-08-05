import unittest
from datetime import date

from fake_farm_data_generator.core.generation import (
    deterministic_operation_date,
    feature_field_identity,
    idw_value,
    ordinary_kriging_value,
    ordinary_kriging_weights,
    normalize_timezone_label,
    parse_years,
    semivariance,
    stable_seed,
)
from fake_farm_data_generator.core.units import unit_system


class GenerationHelperTests(unittest.TestCase):
    def test_field_identity_carries_conventional_columns(self):
        class Fields:
            @staticmethod
            def names():
                return ["field_id", "field_name", "farm", "grower_name"]

        class Feature:
            values = {
                "field_id": "F-19",
                "field_name": "North 80",
                "farm": "Home Farm",
                "grower_name": "Example Grower",
            }

            @staticmethod
            def fields():
                return Fields()

            @classmethod
            def attribute(cls, name):
                return cls.values[name]

        self.assertEqual(
            feature_field_identity(Feature(), 1),
            {
                "field_id": "F-19",
                "field_name": "North 80",
                "farm_name": "Home Farm",
                "grower_name": "Example Grower",
            },
        )

    def test_stable_seed_is_repeatable_and_partitioned(self):
        first = stable_seed(42, "Field_001", 2025, "soil")
        self.assertEqual(first, stable_seed(42, "Field_001", 2025, "soil"))
        self.assertNotEqual(first, stable_seed(42, "Field_001", 2025, "yield"))

    def test_parse_years_supports_ranges_and_lists(self):
        self.assertEqual(parse_years("2020-2022, 2024"), [2020, 2021, 2022, 2024])

    def test_parse_years_enforces_limit(self):
        with self.assertRaisesRegex(ValueError, "No more than 10"):
            parse_years("2010-2020")

    def test_operation_date_stays_inside_window(self):
        result = deterministic_operation_date(2025, 11, 10, 14, 123)
        self.assertGreaterEqual(result, date(2025, 10, 27))
        self.assertLessEqual(result, date(2025, 11, 24))
        self.assertEqual(result, deterministic_operation_date(2025, 11, 10, 14, 123))

    def test_timezone_label_is_optional_and_trimmed(self):
        self.assertEqual(normalize_timezone_label(None), "")
        self.assertEqual(
            normalize_timezone_label("  America/Indianapolis  "),
            "America/Indianapolis",
        )

    def test_timezone_label_rejects_unsafe_or_oversized_values(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            normalize_timezone_label("America/Indiana\npolis")
        with self.assertRaisesRegex(ValueError, "100 characters"):
            normalize_timezone_label("x" * 101)

    def test_idw_returns_exact_sample(self):
        value, count = idw_value([(0, 0, 10), (10, 0, 20)], 0, 0)
        self.assertEqual(value, 10)
        self.assertEqual(count, 1)

    def test_idw_midpoint(self):
        value, count = idw_value([(0, 0, 10), (10, 0, 20)], 5, 0)
        self.assertAlmostEqual(value, 15)
        self.assertEqual(count, 2)

    def test_semivariance_models_are_bounded(self):
        for model in ("Spherical", "Exponential", "Gaussian"):
            self.assertEqual(semivariance(0, model, 100, 0.1), 0)
            self.assertGreater(semivariance(25, model, 100, 0.1), 0)
            self.assertLessEqual(semivariance(1000, model, 100, 0.1), 1)

    def test_ordinary_kriging_returns_exact_sample(self):
        value, count, variance = ordinary_kriging_value(
            [(0, 0, 10), (10, 0, 20), (0, 10, 30)],
            0,
            0,
            range_distance=20,
        )
        self.assertEqual(value, 10)
        self.assertEqual(count, 1)
        self.assertEqual(variance, 0)

    def test_ordinary_kriging_preserves_constant_field(self):
        samples = [(0, 0, 17), (10, 0, 17), (0, 10, 17), (10, 10, 17)]
        value, count, variance = ordinary_kriging_value(
            samples,
            5,
            5,
            model="Spherical",
            range_distance=25,
            nugget_ratio=0.05,
            max_neighbors=4,
        )
        self.assertAlmostEqual(value, 17)
        self.assertEqual(count, 4)
        self.assertGreaterEqual(variance, 0)

    def test_ordinary_kriging_weights_sum_to_one(self):
        _indexes, weights, _variance = ordinary_kriging_weights(
            [(0, 0), (10, 0), (0, 10), (10, 10)],
            4,
            6,
            model="Gaussian",
            range_distance=30,
            max_neighbors=4,
        )
        self.assertAlmostEqual(sum(weights), 1.0)

    def test_unit_system_converts_equivalent_machine_settings(self):
        imperial = unit_system("Imperial")
        metric = unit_system("Metric")
        self.assertAlmostEqual(imperial.distance_to_meters(40), metric.distance_to_meters(12.192))
        self.assertAlmostEqual(imperial.small_distance_to_meters(30), metric.small_distance_to_meters(76.2))
        self.assertAlmostEqual(imperial.speed_to_meters_per_second(5), metric.speed_to_meters_per_second(8.04672))

    def test_metric_and_imperial_seed_spacing_are_equivalent(self):
        imperial = unit_system("Imperial")
        metric = unit_system("Metric")
        inches = imperial.seed_spacing(32000, 30)
        centimeters = metric.seed_spacing(32000 * 2.4710538147, 76.2)
        self.assertAlmostEqual(inches * 2.54, centimeters, places=5)


if __name__ == "__main__":
    unittest.main()
