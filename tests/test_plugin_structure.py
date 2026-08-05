import configparser
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "fake_farm_data_generator"


class PluginStructureTests(unittest.TestCase):
    def test_metadata_declares_processing_provider(self):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(PLUGIN / "metadata.txt", encoding="utf-8")
        metadata = parser["general"]
        self.assertEqual(metadata["name"], "Fake Farm Data Generator")
        self.assertEqual(metadata.getboolean("hasProcessingProvider"), True)
        self.assertEqual(metadata["qgisMinimumVersion"], "3.28")
        self.assertEqual(
            metadata["icon"], "resources/fake_farm_data_generator.png"
        )
        self.assertTrue((PLUGIN / metadata["icon"]).is_file())
        self.assertGreater((PLUGIN / metadata["icon"]).stat().st_size, 100_000)

    def test_provider_registers_five_algorithms(self):
        source = (PLUGIN / "provider.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("self.addAlgorithm("), 5)

    def test_soil_vertical_slice_contains_reviewed_features(self):
        source = (PLUGIN / "algorithms" / "soil_tests.py").read_text(
            encoding="utf-8"
        )
        for expected in (
            'PLACEMENT_OPTIONS = ["Regular Grid", "Random"]',
            'UNIT_OPTIONS = ["ppm", "lb/acre"]',
            'INTERPOLATION_OPTIONS = ["IDW", "Ordinary Kriging"]',
            'KRIGING_MODEL_OPTIONS = ["Spherical", "Exponential", "Gaussian"]',
            '"surface_method", interpolation_method',
        ):
            self.assertIn(expected, source)
        generation = (PLUGIN / "core" / "generation.py").read_text(encoding="utf-8")
        for expected in ('"Low": 0.5', '"Medium": 1.5', '"High": 3.0'):
            self.assertIn(expected, generation)

    def test_planting_generator_contains_v1_outputs(self):
        source = (PLUGIN / "algorithms" / "planting.py").read_text(encoding="utf-8")
        for expected in (
            'POINT_OUTPUT_OPTIONS = ["Planter Center", "Row Units", "Both"]',
            '"Singulation": "singulation_pct"',
            '"Ground Contact": "ground_contact_pct"',
            '"Clean Furrow": "clean_furrow_pct"',
            '"planting_center",',
            '"planting_row_unit",',
            'surface_method = "generated_centroid"',
        ):
            self.assertIn(expected, source)

    def test_application_generator_contains_v1_operations(self):
        source = (PLUGIN / "algorithms" / "applications.py").read_text(
            encoding="utf-8"
        )
        for expected in (
            '"Dry Fertilizer"',
            '"Liquid Fertilizer"',
            '"Lime"',
            '"Chemical Spraying"',
            '"Manure"',
            '"Seeding or Broadcast Seeding"',
            'RATE_MODE_OPTIONS = ["Flat Rate", "Variable Rate"]',
            '"fake_terrain_effect"',
        ):
            self.assertIn(expected, source)

    def test_yield_generator_contains_v1_crop_profiles(self):
        source = (PLUGIN / "algorithms" / "yield_data.py").read_text(encoding="utf-8")
        for expected in (
            '"Corn"',
            '"Soybeans"',
            '"Cotton"',
            '"Sunflowers"',
            '"Alfalfa"',
            '"Other Crop"',
            '"dry_yield"',
            '"wet_yield"',
            '"moisture_pct"',
        ):
            self.assertIn(expected, source)

    def test_complete_run_orchestrates_all_generators(self):
        source = (PLUGIN / "algorithms" / "complete_dataset.py").read_text(
            encoding="utf-8"
        )
        for algorithm_id in (
            "create_fake_soil_test_data",
            "create_fake_planting_data",
            "create_fake_as_applied_data",
            "create_fake_yield_data",
        ):
            self.assertIn(algorithm_id, source)
        self.assertIn("APPLICATION_OPERATIONS_JSON", source)
        self.assertIn("operation_to_processing_parameters", source)
        self.assertIn("consolidate_complete_run_geopackages", source)
        consolidation = (PLUGIN / "core" / "gpkg_consolidation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('f"fake_farm_data_{year}.gpkg"', consolidation)
        self.assertIn('manifest["yearly_geopackages"]', consolidation)

    def test_consolidation_uses_ogr_bulk_feature_copy(self):
        consolidation = (PLUGIN / "core" / "gpkg_consolidation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("target_feature.SetFrom(source_feature, 1)", consolidation)
        self.assertNotIn("target_feature.SetField(", consolidation)

    def test_complete_run_contains_reviewable_cdl_resolution(self):
        complete = (PLUGIN / "algorithms" / "complete_dataset.py").read_text(
            encoding="utf-8"
        )
        for expected in (
            'CROP_LOOKUP_OPTIONS = ["Manual profile", "Automatic CDL"]',
            "resolve_field_year_assignments",
            "CROP_OVERRIDES_JSON",
            "CROP_PROVENANCE_JSON",
        ):
            self.assertIn(expected, complete)
        resolver = (PLUGIN / "crops" / "resolver.py").read_text(encoding="utf-8")
        self.assertIn("threshold: float = 0.40", resolver)
        manager = (PLUGIN / "crops" / "manager.py").read_text(encoding="utf-8")
        self.assertIn("remote.cached", manager)
        self.assertIn("local_cdl", manager)
        self.assertIn("remote.fetch", manager)

    def test_plugin_exposes_custom_complete_run_dialog(self):
        dialog = (PLUGIN / "complete_dialog.py").read_text(encoding="utf-8")
        for tab in (
            '"General"',
            '"Crops"',
            '"Soil Tests"',
            '"Planting"',
            '"Applications"',
            '"Yield"',
            '"Outputs and Review"',
        ):
            self.assertIn(tab, dialog)
        plugin = (PLUGIN / "plugin.py").read_text(encoding="utf-8")
        self.assertIn("Create Complete Fake Farm Dataset", plugin)
        self.assertIn("open_complete_dialog", plugin)
        self.assertIn("QIcon", plugin)
        self.assertIn("addToolBarIcon", plugin)
        self.assertIn("QTableWidget", dialog)
        self.assertIn("Add selected years", dialog)
        self.assertIn("_duplicate_application_row", dialog)
        self.assertIn('QPushButton("Run Reviewed Configuration")', dialog)
        self.assertIn("build_preflight_review_text", dialog)
        self.assertIn("Pull Crops from USDA CDL", dialog)
        self.assertIn("Field boundary layers (check one or more)", dialog)
        self.assertIn('form.insertRow(0, "Parent output directory (required)"', dialog)
        self.assertIn("Headland planter passes", dialog)
        self.assertIn("Boundary setback for sample points", dialog)
        self.assertIn('form.addRow("Data to create"', dialog)
        self.assertIn('"America/Chicago"', dialog)
        self.assertIn('crop_source="user_override"', dialog)
        self.assertIn("QProcess", dialog)
        self.assertIn("qgis_process", dialog)
        self.assertIn('serialized = ",".join(', dialog)

    def test_portable_review_uses_branded_single_field_swipe_layout(self):
        review = (PLUGIN / "review" / "builder.py").read_text(encoding="utf-8")
        for expected in (
            'id="handle"',
            'id="fieldFilter"',
            'fake_farm_data_generator.png',
            "rightChooser.hidden=!enabled",
            "leftWrap.style.width=enabled?swipe.value+'%':'100%'",
            "function zoomToField(fieldId)",
            "fieldSelect.onchange=",
            "selectableLayers=layers.filter",
            "function allBoundaryFeatures()",
            "function boundaryContains(feature,latlng)",
            "function fieldAtLatLng(latlng)",
            "function chooseFieldAtLatLng(event)",
            "left.on('click',chooseFieldAtLatLng)",
            "chooseField(fieldId);if(event.originalEvent)L.DomEvent.stopPropagation",
            ".style.zIndex=650",
            "function refreshBoundaries()",
            'id="layerOpacity"',
            "function preferredAttribute(item)",
            "?'dry_yield'",
            "?'population'",
            "?'actual_rate'",
            "?'pH'",
            "minimumFractionDigits:1,maximumFractionDigits:1",
            "setCompare(false)",
        ):
            self.assertIn(expected, review)
        self.assertNotIn('id="compareToggle" type="checkbox" checked', review)
        for removed in ("Run manifest</a>", "Run recipe</a>", "Generated files ("):
            self.assertNotIn(removed, review)

    def test_complete_run_emits_explicit_overall_progress(self):
        orchestrator = (PLUGIN / "algorithms" / "complete_dataset.py").read_text(
            encoding="utf-8"
        )
        dialog = (PLUGIN / "complete_dialog.py").read_text(encoding="utf-8")
        self.assertIn("FFDG_OVERALL_PROGRESS|", orchestrator)
        self.assertIn(r"FFDG_OVERALL_PROGRESS\|", dialog)
        self.assertNotIn(r"(?<!\d)(\d{1,3})%", dialog)

    def test_yield_restores_original_natural_pattern_and_perimeter_headlands(self):
        source = (PLUGIN / "algorithms" / "yield_data.py").read_text(encoding="utf-8")
        planting = (PLUGIN / "algorithms" / "planting.py").read_text(encoding="utf-8")
        for expected in (
            'stable_seed(field_seed, "natural_yield_pattern")',
            "wave_1 = math.sin",
            "wave_2 = math.cos",
            "wave_3 = math.sin",
            "_operation_passes",
            "_line_heading",
        ):
            self.assertIn(expected, source)
        for expected in (
            "_headland_lines",
            "headland_width = max(0, int(headland_passes)) * swath_width",
            "inset.asMultiPolygon()",
        ):
            self.assertIn(expected, planting)


if __name__ == "__main__":
    unittest.main()
