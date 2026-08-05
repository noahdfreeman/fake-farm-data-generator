import tempfile
import unittest
from pathlib import Path

from fake_farm_data_generator.core.preflight_review import (
    build_preflight_review_text,
    estimate_runtime_range,
    runtime_warning,
    runtime_estimate_text,
)


class PreflightReviewTests(unittest.TestCase):
    def test_review_contains_every_required_section_and_estimate(self):
        estimates = {
            "soil_points": 20,
            "soil_surface_cells": 100,
            "planter_center_points": 200,
            "planting_row_unit_points": 3200,
            "planting_surface_cells": 100,
            "application_points": 150,
            "application_surface_cells": 100,
            "yield_points": 180,
            "yield_surface_cells": 100,
            "total_points": 3750,
            "total_surface_cells": 400,
            "total_records": 4150,
        }
        with tempfile.TemporaryDirectory() as folder:
            text = build_preflight_review_text(
                field_count=2,
                used_selection=True,
                area_text="123.4 acres",
                years=[2024, 2025],
                enabled={
                    "soil": True,
                    "planting": True,
                    "applications": True,
                    "yield": True,
                },
                estimates=estimates,
                output_formats=["GeoPackage", "GeoJSON"],
                operation_count=2,
                crop_mode="Automatic CDL",
                crop_review_status="4 field-year assignments reviewed",
                network_requirement="USDA CroplandCROS may be contacted",
                output_directory=folder,
                timezone_label="America/Indianapolis",
                review_max_features=5000,
                runtime_estimate="about 10s to 30s",
            )
        for expected in (
            "RUN SCOPE",
            "2 (selected polygon features only)",
            "Years: 2024, 2025",
            "Soil tests, Planting, As-applied, Yield",
            "CROP REVIEW AND NETWORK",
            "4 field-year assignments reviewed",
            "Soil-test points: 20",
            "Planting row-unit points: 3,200",
            "Total records: 4,150",
            "Estimated runtime: about 10s to 30s",
            "Formats: GeoPackage, GeoJSON",
            str(Path(folder)),
            "America/Indianapolis",
            "HTML review feature limit per high-volume layer: 5,000",
            "Every soil-test point is included",
            "WARNINGS",
        ):
            self.assertIn(expected, text)

    def test_runtime_warning_scales_with_record_count(self):
        self.assertIn("Normal-sized", runtime_warning(99_999))
        self.assertIn("Large run", runtime_warning(100_000))
        self.assertIn("Very large", runtime_warning(1_000_000))

    def test_runtime_estimate_scales_with_work_and_output_formats(self):
        small = {"soil_points": 100, "total_records": 100}
        large = {
            "yield_points": 500_000,
            "yield_surface_cells": 100_000,
            "total_records": 600_000,
        }
        small_range = estimate_runtime_range(small, ["GeoPackage"], 5_000)
        large_range = estimate_runtime_range(
            large, ["GeoPackage", "GeoJSON", "Shapefile"], 20_000
        )
        self.assertLess(small_range[0], small_range[1])
        self.assertGreater(large_range[0], small_range[0])
        self.assertIn("about", runtime_estimate_text(large))

    def test_runtime_estimate_tracks_optimized_reference_run(self):
        reference = {
            "soil_points": 79,
            "soil_surface_cells": 9_443,
            "planter_center_points": 86_916,
            "planting_row_unit_points": 0,
            "planting_surface_cells": 28_329,
            "application_points": 28_974,
            "application_surface_cells": 28_329,
            "yield_points": 144_858,
            "yield_surface_cells": 28_329,
            "total_records": 355_257,
        }
        lower, upper = estimate_runtime_range(reference, ["GeoPackage"], 20_000)
        self.assertLessEqual(lower, 44)
        self.assertGreaterEqual(upper, 44)
        self.assertLess(upper, 90)


if __name__ == "__main__":
    unittest.main()
