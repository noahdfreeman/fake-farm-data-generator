import unittest

from fake_farm_data_generator.core.application_operations import (
    normalize_application_operations,
)
from fake_farm_data_generator.core.point_estimator import estimate_complete_records


class PointEstimatorTests(unittest.TestCase):
    def test_all_generators_have_nonzero_estimates(self):
        operations = normalize_application_operations("", [2024, 2025])
        estimates = estimate_complete_records(
            404685.64224,
            [2024, 2025],
            {"soil": True, "planting": True, "applications": True, "yield": True},
            3,
            "Imperial",
            operations,
        )
        for key in (
            "soil_points",
            "soil_surface_cells",
            "planter_center_points",
            "planting_surface_cells",
            "application_points",
            "application_surface_cells",
            "yield_points",
            "yield_surface_cells",
        ):
            self.assertGreater(estimates[key], 0, key)
        self.assertEqual(estimates["planting_row_unit_points"], 0)
        self.assertEqual(
            estimates["total_records"],
            estimates["total_points"] + estimates["total_surface_cells"],
        )

    def test_metric_and_imperial_defaults_are_equivalent(self):
        area = 404685.64224
        imperial_operations = normalize_application_operations("", [2025])
        metric_operations = normalize_application_operations("", [2025])
        for operation in metric_operations:
            operation.update(
                equipment_width=18.288,
                nominal_speed=16.09344,
                headland_passes=2,
                surface_grid_size=9.144,
            )
        enabled = {"soil": True, "planting": True, "applications": True, "yield": True}
        imperial = estimate_complete_records(
            area, [2025], enabled, 3, "Imperial", imperial_operations
        )
        metric = estimate_complete_records(
            area, [2025], enabled, 3, "Metric", metric_operations
        )
        for key in (
            "soil_surface_cells",
            "planting_surface_cells",
            "application_surface_cells",
            "yield_surface_cells",
        ):
            self.assertEqual(imperial[key], metric[key], key)
        for key, tolerance in (
            ("planter_center_points", 1),
            ("planting_row_unit_points", 16),
            ("application_points", 1),
            ("yield_points", 1),
        ):
            self.assertLessEqual(abs(imperial[key] - metric[key]), tolerance, key)
        self.assertLessEqual(abs(imperial["soil_points"] - metric["soil_points"]), 1)

    def test_disabled_generators_estimate_zero(self):
        estimates = estimate_complete_records(
            10000,
            [2025],
            {"soil": False, "planting": False, "applications": False, "yield": False},
            3,
            0,
            [],
        )
        self.assertEqual(estimates["total_records"], 0)

    def test_explicit_soil_schedule_controls_estimated_year_count(self):
        one_year = estimate_complete_records(
            40468.564224,
            [2020, 2021, 2022, 2023, 2024],
            {"soil": True},
            1,
            "Imperial",
            [],
            soil_years=[2021],
        )
        two_years = estimate_complete_records(
            40468.564224,
            [2020, 2021, 2022, 2023, 2024],
            {"soil": True},
            1,
            "Imperial",
            [],
            soil_years=[2021, 2023],
        )
        self.assertEqual(two_years["soil_points"], one_year["soil_points"] * 2)
        self.assertEqual(
            two_years["soil_surface_cells"], one_year["soil_surface_cells"] * 2
        )


if __name__ == "__main__":
    unittest.main()
