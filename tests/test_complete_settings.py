import json
import unittest

from fake_farm_data_generator.core.complete_settings import (
    normalize_planting_settings,
    resolve_soil_schedule,
    normalize_soil_settings,
    normalize_yield_settings,
    planting_processing_parameters,
    soil_processing_parameters,
    yield_processing_parameters,
)


class CompleteSettingsTests(unittest.TestCase):
    def test_blank_metric_settings_use_converted_defaults(self):
        soil = normalize_soil_settings("", "Metric")
        planting = normalize_planting_settings("", "Metric")
        yield_settings = normalize_yield_settings("", "Metric")
        self.assertAlmostEqual(soil["surface_grid_size"], 9.144)
        self.assertAlmostEqual(soil["boundary_setback"], 45.72)
        self.assertAlmostEqual(planting["planter_width"], 12.192)
        self.assertAlmostEqual(planting["row_spacing"], 76.2)
        self.assertEqual(planting["point_output"], "Planter Center")
        self.assertAlmostEqual(
            planting["crop_profiles"]["Soybeans"]["target_population"],
            140000 * 2.4710538147,
        )
        self.assertIn("Singulation", planting["surface_attributes"])
        self.assertAlmostEqual(yield_settings["nominal_speed"], 6.437376)
        self.assertEqual(planting["headland_passes"], 2)
        self.assertEqual(yield_settings["headland_passes"], 3)

    def test_soil_kriging_settings_map_to_processing_parameters(self):
        settings = normalize_soil_settings(
            json.dumps(
                {
                    "placement": "Random",
                    "interpolation_method": "Ordinary Kriging",
                    "kriging_model": "Gaussian",
                    "kriging_range": 450,
                    "kriging_nugget": 0.2,
                    "max_neighbors": 18,
                    "p_unit": "kg/ha",
                }
            )
        )
        parameters = soil_processing_parameters(settings)
        self.assertEqual(parameters["PLACEMENT"], 1)
        self.assertEqual(parameters["INTERPOLATION_METHOD"], 1)
        self.assertEqual(parameters["KRIGING_MODEL"], 2)
        self.assertEqual(parameters["P_UNIT"], 1)
        self.assertEqual(parameters["KRIGING_RANGE"], 450)
        self.assertEqual(parameters["BOUNDARY_SETBACK"], 150.0)

    def test_unattributed_soil_disables_surface(self):
        settings = normalize_soil_settings(json.dumps({"unattributed": True}))
        self.assertFalse(settings["create_surface"])

    def test_planting_settings_map_selected_outputs(self):
        settings = normalize_planting_settings(
            json.dumps(
                {
                    "point_output": "Row Units",
                    "surface_attributes": ["Population", "Seed Depth"],
                    "direction_mode": "Manual",
                    "manual_bearing": 92,
                }
            )
        )
        parameters = planting_processing_parameters(settings)
        self.assertEqual(parameters["POINT_OUTPUT"], 1)
        self.assertEqual(parameters["SURFACE_ATTRIBUTES"], [0, 3])
        self.assertEqual(parameters["DIRECTION_MODE"], 1)
        self.assertEqual(parameters["HEADLAND_PASSES"], 2)

    def test_invalid_population_bounds_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "min_population"):
            normalize_planting_settings(
                json.dumps(
                    {
                        "min_population": 40000,
                        "target_population": 32000,
                        "max_population": 38000,
                    }
                )
            )

    def test_crop_specific_planting_profiles_validate(self):
        settings = normalize_planting_settings(
            {
                "crop_profiles": {
                    "Soybeans": {
                        "min_population": 110000,
                        "target_population": 145000,
                        "max_population": 175000,
                        "seed_depth": 1.25,
                        "planting_date": "05-12",
                    }
                }
            }
        )
        self.assertEqual(
            settings["crop_profiles"]["Soybeans"]["target_population"], 145000
        )
        with self.assertRaisesRegex(ValueError, "Soybeans population"):
            normalize_planting_settings(
                {
                    "crop_profiles": {
                        "Soybeans": {
                            "min_population": 160000,
                            "target_population": 140000,
                            "max_population": 150000,
                            "seed_depth": 1.25,
                            "planting_date": "05-12",
                        }
                    }
                }
            )

    def test_yield_settings_map_machine_and_date_controls(self):
        settings = normalize_yield_settings(
            json.dumps(
                {
                    "swath_width": 35,
                    "headland_penalty": 15,
                    "harvest_date": "09-25",
                    "variability_level": "High",
                }
            )
        )
        parameters = yield_processing_parameters(settings)
        self.assertEqual(parameters["SWATH_WIDTH"], 35)
        self.assertEqual(parameters["HEADLAND_PENALTY"], 15)
        self.assertEqual(parameters["HARVEST_MONTH_DAY"], "09-25")
        self.assertEqual(parameters["VARIABILITY_LEVEL"], 2)
        self.assertEqual(parameters["HEADLAND_PASSES"], 3)

    def test_legacy_headland_widths_migrate_to_pass_counts(self):
        planting = normalize_planting_settings(
            {"planter_width": 40, "headland_width": 80}
        )
        yield_settings = normalize_yield_settings(
            {"swath_width": 30, "headland_width": 80}
        )
        self.assertEqual(planting["headland_passes"], 2)
        self.assertEqual(yield_settings["headland_passes"], 3)

    def test_soil_schedule_accepts_explicit_first_and_final_years(self):
        self.assertEqual(
            resolve_soil_schedule([2020, 2021, 2022, 2023, 2024], 2, "2021", "2024"),
            [2021, 2023],
        )
        with self.assertRaisesRegex(ValueError, "within the complete-run years"):
            resolve_soil_schedule([2022, 2023], 1, "2021", "2023")

    def test_yield_profile_overrides_validate_ranges(self):
        settings = normalize_yield_settings(
            {
                "profile_overrides": {
                    "Corn": {
                        "min_yield": 150,
                        "max_yield": 210,
                        "min_moisture": 12,
                        "max_moisture": 24,
                        "standard_moisture": 15.5,
                    }
                }
            }
        )
        self.assertEqual(settings["profile_overrides"]["Corn"]["min_yield"], 150)
        with self.assertRaisesRegex(ValueError, "minimum <= standard <= maximum"):
            normalize_yield_settings(
                {
                    "profile_overrides": {
                        "Corn": {
                            "min_yield": 150,
                            "max_yield": 210,
                            "min_moisture": 20,
                            "max_moisture": 24,
                            "standard_moisture": 15.5,
                        }
                    }
                }
            )


if __name__ == "__main__":
    unittest.main()
