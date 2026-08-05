"""Headless live-QGIS smoke test for the initial plugin build."""

from __future__ import annotations

import json
import gc
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsProcessingParameterDefinition,
    QgsRasterLayer,
    QgsProject,
    QgsVectorLayer,
)


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PARENT = Path(os.environ.get("FAKE_FARM_PLUGIN_PARENT", str(ROOT)))
sys.path.insert(0, str(PLUGIN_PARENT))


def trace(message):
    if os.environ.get("FAKE_FARM_SMOKE_TRACE") == "1":
        print(f"FFDG_SMOKE_STAGE {message}", flush=True)


class RecordingFeedback(QgsProcessingFeedback):
    def __init__(self):
        super().__init__()
        self.info_messages = []

    def pushInfo(self, message):
        self.info_messages.append(str(message))
        super().pushInfo(message)


class CancelOnPreflightFeedback(RecordingFeedback):
    def pushInfo(self, message):
        super().pushInfo(message)
        if str(message).startswith("Preflight estimate:"):
            self.cancel()


def assert_layer(path: str, required_fields, forbidden_fields=()):
    layer = QgsVectorLayer(path, Path(str(path).split("|", 1)[0]).stem, "ogr")
    if not layer.isValid():
        raise AssertionError(f"Could not open output layer: {path}")
    if layer.featureCount() <= 0:
        raise AssertionError(f"Output layer is empty: {path}")
    names = set(layer.fields().names())
    missing = set(required_fields) - names
    if missing:
        raise AssertionError(f"{path} is missing fields: {sorted(missing)}")
    present_forbidden = set(forbidden_fields) & names
    if present_forbidden:
        raise AssertionError(
            f"{path} unexpectedly contains fields: {sorted(present_forbidden)}"
        )
    return layer.featureCount(), names


def attribute_values(path: str, field_name: str):
    layer = QgsVectorLayer(path, Path(str(path).split("|", 1)[0]).stem, "ogr")
    if not layer.isValid():
        raise AssertionError(f"Could not open output layer: {path}")
    values = [float(feature[field_name]) for feature in layer.getFeatures()]
    del layer
    return values


def text_attribute_values(path: str, field_name: str):
    layer = QgsVectorLayer(path, Path(str(path).split("|", 1)[0]).stem, "ogr")
    if not layer.isValid():
        raise AssertionError(f"Could not open output layer: {path}")
    values = [str(feature[field_name]) for feature in layer.getFeatures()]
    del layer
    return values


def assert_perimeter_headlands(path: str, label: str):
    """Require curved headland records around all sides, not one end-row axis."""

    layer = QgsVectorLayer(path, f"{label}_headlands", "ogr")
    if not layer.isValid():
        raise AssertionError(f"Could not open {label} headland layer: {path}")
    headland_headings = {
        int(round(float(feature["heading"]) / 30.0)) % 12
        for feature in layer.getFeatures()
        if bool(feature["is_headland"])
    }
    del layer
    if len(headland_headings) < 4:
        raise AssertionError(
            f"{label} did not create curved full-perimeter headland passes"
        )


def main() -> None:
    trace("start")
    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
        plugins_path = Path(prefix) / "python" / "plugins"
        if plugins_path.is_dir() and str(plugins_path) not in sys.path:
            sys.path.insert(0, str(plugins_path))
    app = QgsApplication([], False)
    app.initQgis()
    provider = None
    temporary_root = Path(tempfile.mkdtemp(prefix="fake_farm_data_smoke_"))
    try:
        from processing.core.Processing import Processing

        Processing.initialize()
        from fake_farm_data_generator.complete_dialog import CompleteDatasetDialog
        from fake_farm_data_generator.algorithms.complete_dataset import (
            CreateCompleteFakeFarmDatasetAlgorithm,
        )
        from fake_farm_data_generator.algorithms.soil_tests import (
            CreateFakeSoilTestsAlgorithm,
        )
        from fake_farm_data_generator.provider import FakeFarmDataGeneratorProvider

        trace("dialog-ui")
        complete_ui_algorithm = CreateCompleteFakeFarmDatasetAlgorithm()
        complete_ui_algorithm.initAlgorithm()
        dialog = complete_ui_algorithm.createCustomParametersWidget(None)
        if not isinstance(dialog, CompleteDatasetDialog):
            raise AssertionError(
                "Complete Processing algorithm did not open the tabbed builder"
            )
        hidden_flag = getattr(QgsProcessingParameterDefinition, "FlagHidden", None)
        if hidden_flag is None:
            hidden_flag = QgsProcessingParameterDefinition.Flag.FlagHidden
        transport_names = {
            complete_ui_algorithm.SOIL_SETTINGS_JSON,
            complete_ui_algorithm.PLANTING_SETTINGS_JSON,
            complete_ui_algorithm.APPLICATION_OPERATIONS_JSON,
            complete_ui_algorithm.YIELD_SETTINGS_JSON,
            complete_ui_algorithm.CROP_OVERRIDES_JSON,
            complete_ui_algorithm.CROP_ASSIGNMENTS_JSON,
        }
        if any(
            parameter.name() in transport_names
            and not parameter.flags() & hidden_flag
            for parameter in complete_ui_algorithm.parameterDefinitions()
        ):
            raise AssertionError("Complete Processing UI still exposes JSON settings")
        if dialog.tabs.count() != 7:
            raise AssertionError("Complete-run dialog does not expose the seven v1 tabs")
        expected_tabs = [
            "General",
            "Crops",
            "Soil Tests",
            "Planting",
            "Applications",
            "Yield",
            "Outputs and Review",
        ]
        if [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] != expected_tabs:
            raise AssertionError("Complete-run dialog tab order is incorrect")
        if dialog.application_table.rowCount() != 1:
            raise AssertionError("Applications tab did not start with a baseline operation")
        initial_operation = dialog._application_rows()[0]
        planting_headland_width = (
            dialog.planting_headland_passes.value() * dialog.planter_width.value()
        )
        yield_headland_width = (
            dialog.yield_headland_passes.value() * dialog.yield_swath.value()
        )
        if (
            abs(dialog.soil_boundary_setback.value() - 150.0) > 0.001
            or dialog.planting_headland_passes.value() != 2
            or initial_operation["headland_passes"] != 2
            or yield_headland_width < planting_headland_width
            or yield_headland_width - planting_headland_width
            >= dialog.yield_swath.value()
        ):
            raise AssertionError("Setback or pass-count headland defaults were not initialized")
        current_year = datetime.now().year
        if (
            len(dialog.year_buttons) != 10
            or not dialog.year_buttons[current_year].isChecked()
            or dialog._years_text() != str(current_year)
            or dialog.timezone.findData("America/Indianapolis") < 0
            or dialog._timezone_text() != "America/Chicago"
            or any(
                checkbox.isChecked()
                for checkbox in (
                    dialog.create_soil,
                    dialog.create_planting,
                    dialog.create_applications,
                    dialog.create_yield,
                )
            )
        ):
            raise AssertionError("General tab selection controls were not initialized")
        if (
            dialog.planting_crop_tabs.count()
            != len(dialog.planting_crop_controls)
            or abs(
                dialog.planting_crop_controls["Soybeans"]["target_population"].value()
                - 140000
            )
            > 0.1
        ):
            raise AssertionError("Crop-specific planting tabs were not initialized")
        dialog._duplicate_application_row()
        if dialog.application_table.rowCount() != 2:
            raise AssertionError("Applications tab could not duplicate an operation")
        dialog.unit_system.setCurrentIndex(1)
        metric_dialog_operation = dialog._application_rows()[0]
        if (
            abs(metric_dialog_operation["equipment_width"] - 18.288) > 0.0001
            or metric_dialog_operation["rate_unit"] != "kg/ha"
            or abs(dialog.soil_density.value() - 1.011714) > 0.0002
            or abs(dialog.soil_boundary_setback.value() - 45.72) > 0.001
            or dialog.soil_p_unit.itemText(1) != "kg/ha"
            or abs(dialog.planter_width.value() - 12.192) > 0.0001
            or dialog.planting_headland_passes.value() != 2
            or abs(dialog.planter_row_spacing.value() - 76.2) > 0.001
            or abs(dialog.planting_target_population.value() - 79073.7) > 0.2
            or abs(dialog.yield_swath.value() - 9.144) > 0.0001
            or abs(float(dialog.yield_profile_table.item(0, 2).text()) - 7.532448) > 0.001
        ):
            raise AssertionError("Complete dialog did not convert displayed Imperial defaults")
        if (
            dialog._soil_settings()["interpolation_method"] != "Ordinary Kriging"
            or dialog._planting_settings()["point_output"] != "Planter Center"
            or dialog._yield_settings()["variability_level"] != "Medium"
        ):
            raise AssertionError("Complete dialog advanced settings were not initialized")
        dialog.soil_density.setValue(2.25)
        dialog.planting_bearing.setValue(73.0)
        dialog.yield_headland_penalty.setValue(17.0)
        dialog._set_years("2022-2025")
        dialog.soil_first_year.setCurrentIndex(dialog.soil_first_year.findData("2022"))
        dialog.soil_final_year.setCurrentIndex(dialog.soil_final_year.findData("2025"))
        dialog.customize_yield_profiles.setChecked(True)
        dialog.yield_profile_table.item(0, 2).setText("8.25")
        dialog.yield_profile_table.item(0, 3).setText("12.5")
        dialog._set_timezone("America/Indianapolis")
        dialog.review_max_features.setValue(4321)
        saved_dialog_recipe = dialog._dialog_recipe()
        dialog.unit_system.setCurrentIndex(0)
        dialog.soil_density.setValue(9.0)
        dialog.planting_bearing.setValue(0.0)
        dialog.yield_headland_penalty.setValue(1.0)
        dialog.soil_first_year.setCurrentIndex(0)
        dialog.soil_final_year.setCurrentIndex(0)
        dialog.customize_yield_profiles.setChecked(False)
        dialog._set_timezone("")
        dialog.review_max_features.setValue(20000)
        dialog._apply_dialog_recipe(saved_dialog_recipe)
        if (
            dialog.unit_system.currentText() != "Metric"
            or abs(dialog.soil_density.value() - 2.25) > 0.0001
            or abs(dialog.planting_bearing.value() - 73.0) > 0.0001
            or abs(dialog.yield_headland_penalty.value() - 17.0) > 0.0001
            or dialog.soil_first_year.currentData() != "2022"
            or dialog.soil_final_year.currentData() != "2025"
            or not dialog.customize_yield_profiles.isChecked()
            or abs(float(dialog.yield_profile_table.item(0, 2).text()) - 8.25) > 0.0001
            or dialog._timezone_text() != "America/Indianapolis"
            or dialog.review_max_features.value() != 4321
            or saved_dialog_recipe.get("review_max_features") != 4321
            or saved_dialog_recipe.get("fake_warning")
            != "FAKE DATA - NOT FOR AGRONOMIC DECISIONS"
            or dialog.application_table.rowCount() != 2
            or saved_dialog_recipe.get("recipe_type")
            != "fake_farm_data_generator_complete_dialog"
        ):
            raise AssertionError("Complete dialog recipe did not round-trip its settings")
        dialog.close()
        dialog.deleteLater()
        app.processEvents()
        del dialog

        preset_dialog = complete_ui_algorithm.createCustomParametersWidget(None)
        preset_dialog.setParameters(
            {
                "UNIT_SYSTEM": 0,
                "YEARS": "2021-2025",
                "SOIL_FIRST_YEAR": "2022",
                "SOIL_FINAL_YEAR": "2024",
                "SOIL_INTERVAL": 2,
                "YIELD_SETTINGS_JSON": json.dumps(
                    {
                        "headland_penalty": 19,
                        "profile_overrides": {
                            "Corn": {
                                "min_yield": 145,
                                "max_yield": 205,
                                "min_moisture": 12,
                                "max_moisture": 23,
                                "standard_moisture": 15.5,
                            }
                        },
                    }
                ),
            }
        )
        if (
            preset_dialog._years_text() != "2021,2022,2023,2024,2025"
            or preset_dialog.soil_first_year.currentData() != "2022"
            or preset_dialog.soil_final_year.currentData() != "2024"
            or preset_dialog.soil_interval.value() != 2
            or abs(preset_dialog.yield_headland_penalty.value() - 19) > 0.001
            or not preset_dialog.customize_yield_profiles.isChecked()
        ):
            raise AssertionError("Tabbed complete dialog did not accept Processing presets")
        preset_dialog.close()
        preset_dialog.deleteLater()
        app.processEvents()
        del preset_dialog

        installed_root = os.environ.get("FAKE_FARM_EXPECT_PLUGIN_ROOT")
        if installed_root:
            imported_provider = Path(
                sys.modules["fake_farm_data_generator.provider"].__file__
            ).resolve()
            expected_root = Path(installed_root).resolve()
            if expected_root not in imported_provider.parents:
                raise AssertionError(
                    f"Smoke test imported {imported_provider}, not installed root {expected_root}"
                )

        trace("provider")
        provider = FakeFarmDataGeneratorProvider()
        registry = QgsApplication.processingRegistry()
        if not registry.addProvider(provider):
            raise AssertionError("Could not register Fake Farm Data Generator provider")

        expected_algorithms = {
            "create_complete_fake_farm_dataset",
            "create_fake_soil_test_data",
            "create_fake_planting_data",
            "create_fake_as_applied_data",
            "create_fake_yield_data",
        }
        actual = {algorithm.name() for algorithm in provider.algorithms()}
        if actual != expected_algorithms:
            raise AssertionError(
                f"Unexpected provider algorithms: expected {sorted(expected_algorithms)}, got {sorted(actual)}"
            )

        import processing

        algorithm_id = "fake_farm_data_generator:create_fake_soil_test_data"
        fixture = ROOT / "tests" / "fixtures" / "two_fields.geojson"

        from qgis.PyQt.QtWidgets import QMessageBox

        trace("isolated-worker-command")
        background_dialog = CompleteDatasetDialog(None)
        background_layer = QgsVectorLayer(str(fixture), "background_fields", "ogr")
        worker_parameters = {
            "INPUT": background_layer,
            "UNIT_SYSTEM": 0,
            "YEARS": "2025",
            "TIMEZONE": "America/Chicago",
            "CREATE_SOIL": True,
            "CREATE_PLANTING": False,
            "CREATE_APPLICATIONS": False,
            "CREATE_YIELD": False,
            "SOIL_INTERVAL": 3,
            "SOIL_FIRST_YEAR": "2025",
            "SOIL_FINAL_YEAR": "2025",
            "OUTPUT_FORMATS": [0, 2],
            "REVIEW_MAX_FEATURES": 100,
            "RANDOM_SEED": 44101,
            "OUTPUT_DIR": str(temporary_root),
        }
        worker_program = background_dialog._qgis_process_program()
        worker_arguments = background_dialog._qgis_process_arguments(
            {**worker_parameters, "INPUT": str(fixture)}
        )
        if (
            not worker_program
            or "CREATE_SOIL=1" not in worker_arguments
            or "OUTPUT_FORMATS=0,2" not in worker_arguments
            or "OUTPUT_FORMATS=0" in worker_arguments
        ):
            raise AssertionError("Isolated qgis_process worker command is invalid")
        if os.environ.get("FAKE_FARM_TEST_ISOLATED_WORKER") == "1":
            original_information = QMessageBox.information
            original_critical = QMessageBox.critical
            background_errors = []
            QMessageBox.information = lambda *_args, **_kwargs: None
            QMessageBox.critical = lambda *_args, **_kwargs: background_errors.append(
                str(_args[-1]) if _args else "isolated worker failure"
            )
            try:
                background_dialog._run_generation_with_progress(worker_parameters)
                deadline = time.monotonic() + 90
                while (
                    background_dialog._generation_running
                    and time.monotonic() < deadline
                ):
                    app.processEvents()
                    time.sleep(0.01)
            finally:
                QMessageBox.information = original_information
                QMessageBox.critical = original_critical
            if (
                background_dialog._generation_running
                or background_errors
                or background_dialog.output_folder is None
                or not background_dialog.output_folder.exists()
                or not background_dialog._generation_messages
            ):
                raise AssertionError(
                    "Isolated complete-run worker did not return output and progress: "
                    f"errors={background_errors} "
                    f"messages={len(background_dialog._generation_messages)}"
                )
        background_dialog.close()
        background_dialog.deleteLater()
        app.processEvents()
        del background_dialog
        del background_layer

        review_layer = QgsVectorLayer(str(fixture), "crop_review_fields", "ogr")
        from qgis.core import QgsProject
        from fake_farm_data_generator.crops.resolver import CropAssignment
        from fake_farm_data_generator.crops.manager import (
            _rotation_assignment,
            parse_assignment_payload,
        )
        import fake_farm_data_generator.complete_dialog as complete_dialog_module

        known_corn = CropAssignment(
            crop_name="Corn",
            crop_code=1,
            crop_pct=90.0,
            crop_source="croplandcros",
            crop_source_year=2024,
            crop_resolution=30.0,
            crop_lookup_at="2026-08-05T00:00:00-04:00",
            crop_overridden=False,
            cdl_class_name="Corn",
            status="accepted",
            review_required=False,
            valid_agricultural_pixels=100,
            total_pixels=100,
        )
        inferred_soybeans = _rotation_assignment({2024: known_corn}, 2025)
        parsed_inference = parse_assignment_payload(
            json.dumps({"Field_001:2025": inferred_soybeans.to_dict()}),
            ["Corn", "Soybeans"],
        )
        assignment_payload_path = temporary_root / "crop_assignments.json"
        assignment_payload_path.write_text(
            json.dumps({"Field_001:2025": inferred_soybeans.to_dict()}),
            encoding="utf-8",
        )
        parsed_file_inference = parse_assignment_payload(
            f"@{assignment_payload_path}", ["Corn", "Soybeans"]
        )
        if (
            inferred_soybeans.crop_name != "Soybeans"
            or inferred_soybeans.crop_source != "rotation_inference"
            or parsed_inference[("Field_001", 2025)].status != "inferred_rotation"
            or parsed_file_inference[("Field_001", 2025)].crop_name != "Soybeans"
        ):
            raise AssertionError("Missing-year crop rotation inference is not stable")

        QgsProject.instance().addMapLayer(review_layer)
        second_review_layer = QgsVectorLayer(str(fixture), "crop_review_fields_2", "ogr")
        second_review_layer.selectByIds([next(second_review_layer.getFeatures()).id()])
        QgsProject.instance().addMapLayer(second_review_layer)
        trace("crop-dialog")
        crop_dialog = CompleteDatasetDialog(None)
        crop_dialog._set_boundary_layers([review_layer, second_review_layer])
        combined = crop_dialog._combined_boundary_layer()
        if combined.featureCount() != 3:
            raise AssertionError("Complete dialog did not combine checked boundary layers")
        crop_dialog._set_boundary_layers([review_layer])
        crop_dialog.field_id_field.setCurrentText("field_name")
        crop_dialog._set_years("2024-2025")

        def fake_api_crops(features, _crs, _context, years, _profiles, feedback=None):
            assignments = {}
            for field_index, _feature in enumerate(features, start=1):
                for year in years:
                    inferred = year == 2025
                    assignments[(f"Field_{field_index:03d}", year)] = CropAssignment(
                        crop_name="Corn" if year % 2 == 0 else "Soybeans",
                        crop_code=1 if year % 2 == 0 else None,
                        crop_pct=82.5 if not inferred else 0.0,
                        crop_source="rotation_inference" if inferred else "croplandcros",
                        crop_source_year=2024,
                        crop_resolution=30.0,
                        crop_lookup_at="2026-08-05T00:00:00-04:00",
                        crop_overridden=False,
                        cdl_class_name="Corn" if not inferred else None,
                        status="inferred_rotation" if inferred else "accepted",
                        review_required=False,
                        valid_agricultural_pixels=100 if not inferred else 0,
                        total_pixels=100 if not inferred else 0,
                    )
            return assignments, []

        original_api_crops = complete_dialog_module.suggest_api_field_year_assignments
        complete_dialog_module.suggest_api_field_year_assignments = fake_api_crops
        try:
            if not crop_dialog._refresh_crop_review():
                raise AssertionError("USDA crop table could not be populated")
        finally:
            complete_dialog_module.suggest_api_field_year_assignments = original_api_crops
        if crop_dialog.crop_review_table.rowCount() != 4:
            raise AssertionError("Crop review table did not create one row per field-year")
        if crop_dialog.crop_review_table.item(0, 0).text() != "West Field":
            raise AssertionError("Crop review table did not use the mapped field ID column")
        if any(
            crop_dialog.crop_review_table.item(row, 5).text()
            not in {"accepted", "inferred_rotation"}
            for row in range(crop_dialog.crop_review_table.rowCount())
        ):
            raise AssertionError("Crop rows did not retain API/inference status")
        pulled = json.loads(crop_dialog._crop_assignments_json(True))
        if len(pulled) != 4 or pulled["Field_001:2025"]["crop_source"] != "rotation_inference":
            raise AssertionError("Crop table did not serialize API and rotation assignments")
        first_crop_choice = crop_dialog.crop_review_table.cellWidget(0, 2)
        first_crop_choice.setCurrentIndex(first_crop_choice.findData("Soybeans"))
        overridden = json.loads(crop_dialog._crop_assignments_json(True))
        if (
            overridden["Field_001:2024"]["crop_name"] != "Soybeans"
            or overridden["Field_001:2024"]["crop_source"] != "user_override"
            or not overridden["Field_001:2024"]["crop_overridden"]
        ):
            raise AssertionError("Crop dropdown did not retain a user crop override")
        crop_dialog.create_soil.setChecked(True)
        crop_dialog.create_planting.setChecked(False)
        crop_dialog.create_applications.setChecked(False)
        crop_dialog.create_yield.setChecked(False)
        crop_dialog.output_directory.setText(str(temporary_root))
        crop_dialog.review_max_features.setValue(5000)
        crop_dialog.review_generation()
        preflight_text = crop_dialog.preflight_review.toPlainText()
        if (
            crop_dialog.tabs.currentIndex() != crop_dialog.tabs.count() - 1
            or not crop_dialog.execute_button.isEnabled()
            or "Fields: 2 (all layer features)" not in preflight_text
            or "Years: 2024, 2025" not in preflight_text
            or "Data types: Soil tests" not in preflight_text
            or "Soil-test points:" not in preflight_text
            or "Total records:" not in preflight_text
            or "Formats: GeoPackage" not in preflight_text
            or "HTML review feature limit per high-volume layer: 5,000"
            not in preflight_text
            or str(temporary_root) not in preflight_text
            or "QGIS must remain open" not in preflight_text
        ):
            raise AssertionError("Complete dialog did not build the v1 preflight review page")
        crop_dialog.close()
        crop_dialog.deleteLater()
        app.processEvents()
        del crop_dialog
        QgsProject.instance().removeMapLayer(second_review_layer.id())

        trace("soil-grid")
        grid_result = processing.run(
            algorithm_id,
            {
                "INPUT": str(fixture),
                "FIRST_YEAR": 2025,
                "INTERVAL": 3,
                "FINAL_YEAR": "2025",
                "PLACEMENT": 0,
                "SAMPLE_DENSITY": 5.0,
                "BOUNDARY_SETBACK": 150.0,
                "GRID_ROTATION": 15.0,
                "GRID_OFFSET_X": 10.0,
                "GRID_OFFSET_Y": -10.0,
                "SAMPLE_DEPTH": "0-8 inches",
                "LAB_NAME": "Fake Test Lab",
                "FERTILITY_LEVEL": 1,
                "VARIABILITY_LEVEL": 2,
                "P_UNIT": 1,
                "K_UNIT": 0,
                "SAMPLE_MONTH_DAY": "11-10",
                "DATE_WINDOW": 14,
                "CREATE_UNATTRIBUTED": False,
                "CREATE_SURFACE": True,
                "SURFACE_GRID_SIZE": 250.0,
                "INTERPOLATION_METHOD": 1,
                "IDW_POWER": 2.0,
                "MAX_NEIGHBORS": 12,
                "KRIGING_MODEL": 0,
                "KRIGING_RANGE": 0.0,
                "KRIGING_NUGGET": 0.05,
                "REVIEW_MAX_FEATURES": 100,
                "RANDOM_SEED": 12345,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        point_path = grid_result["POINT_LAYERS"].split(";")[0]
        surface_path = grid_result["SURFACE_LAYERS"].split(";")[0]
        point_count, point_fields = assert_layer(
            point_path,
            {
                "fake_data",
                "fake_warning",
                "sample_id",
                "boundary_setback",
                "distance_unit",
                "placement_mode",
                "variability_multiplier",
                "p_unit",
                "k_unit",
                "P",
                "K",
            },
        )
        with closing(sqlite3.connect(point_path)) as connection:
            embedded_metadata = dict(
                connection.execute(
                    "SELECT metadata_key, metadata_value FROM ffdg_run_metadata"
                )
            )
            embedded_registration = connection.execute(
                "SELECT data_type FROM gpkg_contents WHERE table_name='ffdg_run_metadata'"
            ).fetchone()
        if (
            embedded_metadata.get("fake_data") != "true"
            or embedded_metadata.get("status") != "complete"
            or embedded_registration != ("attributes",)
        ):
            raise AssertionError("GeoPackage did not retain registered run metadata")
        surface_count, surface_fields = assert_layer(
            surface_path,
            {
                "fake_data",
                "cell_id",
                "surface_method",
                "source_points",
                "variogram_model",
                "kriging_range",
                "kriging_variance",
                "kriging_fallback",
                "P",
                "K",
            },
        )
        identity_layer = QgsVectorLayer(point_path, "soil_identity", "ogr")
        carried_field_names = {
            str(feature["field_name"]) for feature in identity_layer.getFeatures()
        }
        if carried_field_names != {"West Field", "East Field"}:
            raise AssertionError(
                f"Input field names were not carried into output: {carried_field_names}"
            )
        fixture_layer = QgsVectorLayer(str(fixture), "setback_fixture", "ogr")
        fixture_features = list(fixture_layer.getFeatures())
        working_crs = CreateFakeSoilTestsAlgorithm._working_crs(
            fixture_layer.crs(),
            fixture_features,
            QgsProject.instance().transformContext(),
        )
        to_working = QgsCoordinateTransform(
            fixture_layer.crs(),
            working_crs,
            QgsProject.instance().transformContext(),
        )
        field_geometries = {}
        for field_index, source_feature in enumerate(fixture_features, start=1):
            source_geometry = QgsGeometry(source_feature.geometry())
            source_geometry.transform(to_working)
            field_geometries[f"Field_{field_index:03d}"] = source_geometry
        minimum_setback = float("inf")
        for point_feature in identity_layer.getFeatures():
            point_geometry = QgsGeometry(point_feature.geometry())
            point_geometry.transform(to_working)
            field_geometry = field_geometries[str(point_feature["field_id"])]
            squared_distance, *_ = field_geometry.closestSegmentWithContext(
                point_geometry.asPoint()
            )
            minimum_setback = min(minimum_setback, squared_distance ** 0.5)
        if minimum_setback < 45.0:
            raise AssertionError(
                f"Soil points violated the 150-foot boundary setback: {minimum_setback:.2f} m"
            )
        del fixture_layer
        del identity_layer
        surface_layer = QgsVectorLayer(surface_path, "kriging_surface", "ogr")
        first_surface = next(surface_layer.getFeatures())
        if first_surface["surface_method"] != "Ordinary Kriging":
            raise AssertionError("Soil surface did not record ordinary kriging")
        if first_surface["variogram_model"] != "Spherical":
            raise AssertionError("Soil surface did not record the spherical variogram")
        if first_surface["range_mode"] != "Automatic":
            raise AssertionError("Soil surface did not record automatic kriging range")
        if first_surface["kriging_variance"] is None:
            raise AssertionError("Soil surface did not record kriging variance")
        del first_surface
        del surface_layer
        grid_manifest = json.loads(Path(grid_result["MANIFEST"]).read_text())
        if grid_manifest["status"] != "complete":
            raise AssertionError("Grid run manifest did not finish complete")
        if grid_manifest.get("review_max_features") != 100:
            raise AssertionError("Grid run manifest did not retain the review feature limit")
        if grid_manifest["soil"]["variability_multiplier"] != 3.0:
            raise AssertionError("High variability did not retain the 3.0 multiplier")
        if grid_manifest["soil"]["p_unit"] != "lb/acre":
            raise AssertionError("Phosphorus lb/acre selection was not retained")
        if grid_manifest["soil"]["boundary_setback"] != 150.0:
            raise AssertionError("Soil boundary setback was not retained")
        if grid_manifest["soil"]["interpolation_method"] != "Ordinary Kriging":
            raise AssertionError("Manifest did not retain ordinary kriging")
        if grid_manifest["counts"]["kriging_fallback_cells"] != 0:
            raise AssertionError("The standard kriging fixture unexpectedly used IDW fallback")
        if "fake_farm_data_review.html" not in grid_manifest["outputs"]:
            raise AssertionError("Individual soil run did not create its HTML review")
        grid_review_data = (
            Path(grid_result["OUTPUT_FOLDER"])
            / "fake_farm_data_review_data"
            / "layers.js"
        ).read_text(encoding="utf-8")
        grid_review_layers = json.loads(
            grid_review_data.removeprefix("window.FFDG_LAYERS = ")
            .strip()
            .removesuffix(";")
        )
        grid_soil_points = [
            item
            for item in grid_review_layers
            if item["name"].startswith("fake_soil_tests_")
        ]
        grid_soil_surfaces = [
            item
            for item in grid_review_layers
            if item["name"].startswith("fake_soil_surface_")
        ]
        if not grid_soil_points or any(
            item["displayed"] != item["total"] or item["review_sampling"] != "all"
            for item in grid_soil_points
        ):
            raise AssertionError("Review feature limit incorrectly sampled soil-test points")
        if not grid_soil_surfaces or not any(
            item["total"] > 100
            and item["displayed"] <= 100
            and item["displayed"] < item["total"]
            and item["review_sampling"] == "deterministic_interval"
            for item in grid_soil_surfaces
        ):
            raise AssertionError("Review feature limit did not sample the soil surface")

        trace("soil-random")
        random_result = processing.run(
            algorithm_id,
            {
                "INPUT": str(fixture),
                "FIRST_YEAR": 2024,
                "INTERVAL": 3,
                "FINAL_YEAR": "",
                "PLACEMENT": 1,
                "SAMPLE_DENSITY": 10.0,
                "FERTILITY_LEVEL": 1,
                "VARIABILITY_LEVEL": 0,
                "P_UNIT": 0,
                "K_UNIT": 1,
                "SAMPLE_MONTH_DAY": "11-10",
                "DATE_WINDOW": 14,
                "CREATE_UNATTRIBUTED": True,
                "CREATE_SURFACE": True,
                "RANDOM_SEED": 54321,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        random_point_path = random_result["POINT_LAYERS"].split(";")[0]
        random_count, random_fields = assert_layer(
            random_point_path,
            {"fake_data", "sample_id", "placement_mode", "p_unit", "k_unit"},
            {"P", "K", "pH", "OM"},
        )
        if random_result["SURFACE_LAYERS"]:
            raise AssertionError("Unattributed soil run unexpectedly created a surface")
        random_manifest = json.loads(Path(random_result["MANIFEST"]).read_text())
        if random_manifest["soil"]["surface_created"]:
            raise AssertionError("Unattributed manifest claims a surface was created")
        if random_manifest["soil"]["variability_multiplier"] != 0.5:
            raise AssertionError("Low variability did not retain the 0.5 multiplier")

        trace("planting")
        planting_result = processing.run(
            "fake_farm_data_generator:create_fake_planting_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2025,
                "CROP_NAME": "Corn",
                "POINT_OUTPUT": 2,
                "PLANTER_WIDTH": 120.0,
                "ROW_UNITS": 24,
                "ROW_SPACING": 60.0,
                "TARGET_POPULATION": 32000.0,
                "MIN_POPULATION": 26000.0,
                "MAX_POPULATION": 38000.0,
                "SEED_DEPTH": 2.0,
                "NOMINAL_SPEED": 5.0,
                "LOGGING_INTERVAL": 10.0,
                "HEADLAND_PASSES": 2,
                "DIRECTION_MODE": 1,
                "MANUAL_BEARING": 45.0,
                "PLANTING_MONTH_DAY": "05-01",
                "DATE_WINDOW": 14,
                "TIMEZONE": "America/Indianapolis",
                "VARIABILITY_LEVEL": 1,
                "CREATE_SURFACE": True,
                "SURFACE_GRID_SIZE": 250.0,
                "SURFACE_ATTRIBUTES": list(range(13)),
                "RANDOM_SEED": 24680,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        planting_center_count, _center_fields = assert_layer(
            planting_result["CENTER_LAYER"],
            {
                "fake_data",
                "planting_id",
                "record_type",
                "pass_id",
                "timestamp",
                "timezone",
                "population",
                "seed_spacing",
                "seed_depth",
                "singulation_pct",
                "spacing_quality_pct",
                "skips_pct",
                "ride_quality_pct",
                "ground_contact_pct",
                "furrow_moisture_pct",
                "furrow_temperature",
                "temperature_unit",
                "uniform_furrow_pct",
                "clean_furrow_pct",
                "is_headland",
            },
        )
        planting_row_count, _row_fields = assert_layer(
            planting_result["ROW_LAYER"],
            {
                "fake_data",
                "planting_id",
                "center_point_id",
                "record_type",
                "row_unit",
                "section_on",
                "population",
            },
        )
        if set(text_attribute_values(planting_result["CENTER_LAYER"], "timezone")) != {
            "America/Indianapolis"
        }:
            raise AssertionError("Planting timezone was not propagated")
        assert_perimeter_headlands(planting_result["CENTER_LAYER"], "Planting")
        planting_surface_count, _planting_surface_fields = assert_layer(
            planting_result["SURFACE_LAYER"],
            {
                "fake_data",
                "cell_id",
                "surface_method",
                "source_points",
                "population",
                "speed",
                "seed_spacing",
                "seed_depth",
                "singulation_pct",
                "spacing_quality_pct",
                "skips_pct",
                "ride_quality_pct",
                "ground_contact_pct",
                "furrow_moisture_pct",
                "furrow_temperature",
                "uniform_furrow_pct",
                "clean_furrow_pct",
            },
        )
        planting_center_layer = QgsVectorLayer(
            planting_result["CENTER_LAYER"], "planting_metrics", "ogr"
        )
        first_planting = next(planting_center_layer.getFeatures())
        if not (
            88 <= float(first_planting["singulation_pct"]) <= 100
            and 0 <= float(first_planting["skips_pct"]) <= 12
            and first_planting["temperature_unit"] == "F"
        ):
            raise AssertionError("Advanced planting metrics are outside fake-data bounds")
        del planting_center_layer
        planting_manifest = json.loads(Path(planting_result["MANIFEST"]).read_text())
        if planting_manifest["status"] != "complete":
            raise AssertionError("Planting run manifest did not finish complete")
        if planting_manifest["planting"]["direction_mode"] != "Manual":
            raise AssertionError("Planting run did not retain manual direction")
        if set(planting_manifest["field_bearings"].values()) != {45.0}:
            raise AssertionError("Planting run did not retain the 45-degree bearing")
        if planting_manifest["counts"]["planter_center_points"] != planting_center_count:
            raise AssertionError("Planting center manifest count does not match output")
        if planting_manifest["counts"]["row_unit_points"] != planting_row_count:
            raise AssertionError("Planting row manifest count does not match output")
        if planting_manifest["counts"]["planting_surface_cells"] != planting_surface_count:
            raise AssertionError("Planting surface manifest count does not match output")

        trace("planting-automatic")
        automatic_planting_result = processing.run(
            "fake_farm_data_generator:create_fake_planting_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2024,
                "CROP_NAME": "Soybeans",
                "POINT_OUTPUT": 0,
                "PLANTER_WIDTH": 120.0,
                "ROW_UNITS": 24,
                "ROW_SPACING": 60.0,
                "TARGET_POPULATION": 140000.0,
                "MIN_POPULATION": 120000.0,
                "MAX_POPULATION": 160000.0,
                "NOMINAL_SPEED": 5.0,
                "LOGGING_INTERVAL": 60.0,
                "DIRECTION_MODE": 0,
                "CREATE_SURFACE": False,
                "RANDOM_SEED": 13579,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        automatic_center_count, _automatic_fields = assert_layer(
            automatic_planting_result["CENTER_LAYER"],
            {"fake_data", "crop_name", "heading", "population"},
        )
        if automatic_planting_result["ROW_LAYER"]:
            raise AssertionError("Center-only planting run unexpectedly created row output")
        if automatic_planting_result["SURFACE_LAYER"]:
            raise AssertionError("Planting run with surface disabled unexpectedly created one")
        automatic_manifest = json.loads(
            Path(automatic_planting_result["MANIFEST"]).read_text()
        )
        if automatic_manifest["planting"]["direction_mode"] != "Automatic":
            raise AssertionError("Automatic planting run did not retain direction mode")
        if len(automatic_manifest["field_bearings"]) != 2 or any(
            not 0.0 <= bearing < 180.0
            for bearing in automatic_manifest["field_bearings"].values()
        ):
            raise AssertionError("Automatic planting bearings are missing or invalid")

        trace("applications")
        application_result = processing.run(
            "fake_farm_data_generator:create_fake_as_applied_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2025,
                "OPERATION_ID": "VRA_2025_001",
                "OPERATION_TYPE": 0,
                "PRODUCT_NAME": "Fake Dry Blend",
                "RATE_MODE": 1,
                "TARGET_RATE": 150.0,
                "MIN_RATE": 100.0,
                "MAX_RATE": 200.0,
                "RATE_UNIT": "lb/acre",
                "EQUIPMENT_WIDTH": 120.0,
                "NOMINAL_SPEED": 10.0,
                "LOGGING_INTERVAL": 20.0,
                "HEADLAND_PASSES": 2,
                "DIRECTION_MODE": 0,
                "APPLICATION_MONTH_DAY": "04-15",
                "DATE_WINDOW": 14,
                "TIMEZONE": "America/Indianapolis",
                "VARIABILITY_LEVEL": 1,
                "CREATE_SURFACE": True,
                "SURFACE_GRID_SIZE": 250.0,
                "RANDOM_SEED": 97531,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        application_point_count, _application_fields = assert_layer(
            application_result["POINT_LAYER"],
            {
                "fake_data",
                "application_id",
                "operation_id",
                "operation_type",
                "product_name",
                "rate_mode",
                "target_rate",
                "actual_rate",
                "rate_unit",
                "pass_id",
                "timestamp",
                "timezone",
                "speed",
                "fake_terrain_effect",
            },
        )
        application_surface_count, _application_surface_fields = assert_layer(
            application_result["SURFACE_LAYER"],
            {
                "fake_data",
                "cell_id",
                "operation_id",
                "actual_rate",
                "surface_method",
                "source_points",
                "fake_terrain_effect",
            },
        )
        if set(text_attribute_values(application_result["POINT_LAYER"], "timezone")) != {
            "America/Indianapolis"
        }:
            raise AssertionError("Application timezone was not propagated")
        assert_perimeter_headlands(application_result["POINT_LAYER"], "Application")
        application_rates = attribute_values(
            application_result["POINT_LAYER"], "actual_rate"
        )
        if min(application_rates) < 100.0 or max(application_rates) > 200.0:
            raise AssertionError("Variable application rates exceeded configured bounds")
        if max(application_rates) - min(application_rates) < 5.0:
            raise AssertionError("Variable application rates did not vary materially")
        application_manifest = json.loads(Path(application_result["MANIFEST"]).read_text())
        if application_manifest["status"] != "complete":
            raise AssertionError("Application manifest did not finish complete")
        if application_manifest["application"]["rate_mode"] != "Variable Rate":
            raise AssertionError("Application manifest did not retain variable rate mode")
        if application_manifest["counts"]["application_points"] != application_point_count:
            raise AssertionError("Application manifest point count does not match output")
        if application_manifest["counts"]["surface_cells"] != application_surface_count:
            raise AssertionError("Application manifest surface count does not match output")

        flat_application_result = processing.run(
            "fake_farm_data_generator:create_fake_as_applied_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2024,
                "OPERATION_ID": "FLAT_2024_001",
                "OPERATION_TYPE": 3,
                "PRODUCT_NAME": "Fake Herbicide",
                "RATE_MODE": 0,
                "TARGET_RATE": 15.0,
                "MIN_RATE": 12.0,
                "MAX_RATE": 18.0,
                "RATE_UNIT": "gal/acre",
                "EQUIPMENT_WIDTH": 120.0,
                "NOMINAL_SPEED": 12.0,
                "LOGGING_INTERVAL": 60.0,
                "CREATE_SURFACE": False,
                "RANDOM_SEED": 86420,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        flat_rates = attribute_values(flat_application_result["POINT_LAYER"], "actual_rate")
        if not 0.0 < max(flat_rates) - min(flat_rates) < 6.0:
            raise AssertionError("Flat application logs did not retain bounded variation")
        if flat_application_result["SURFACE_LAYER"]:
            raise AssertionError("Flat application with surface disabled created a surface")

        cancel_feedback = CancelOnPreflightFeedback()
        canceled_application_result = processing.run(
            "fake_farm_data_generator:create_fake_as_applied_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2025,
                "OPERATION_ID": "CANCEL_TEST",
                "OPERATION_TYPE": 0,
                "PRODUCT_NAME": "Fake Cancellation Test",
                "RATE_MODE": 0,
                "TARGET_RATE": 150.0,
                "MIN_RATE": 120.0,
                "MAX_RATE": 180.0,
                "RATE_UNIT": "lb/acre",
                "EQUIPMENT_WIDTH": 120.0,
                "NOMINAL_SPEED": 10.0,
                "LOGGING_INTERVAL": 20.0,
                "CREATE_SURFACE": True,
                "RANDOM_SEED": 24680,
                "OUTPUT_DIR": str(temporary_root),
            },
            feedback=cancel_feedback,
        )
        canceled_manifest = json.loads(
            Path(canceled_application_result["MANIFEST"]).read_text()
        )
        if canceled_manifest["status"] != "incomplete":
            raise AssertionError("Canceled application did not retain an incomplete manifest")
        if "fake_farm_data_review.html" in canceled_manifest.get("outputs", []):
            raise AssertionError("Canceled application incorrectly claimed a complete review")

        yield_feedback = RecordingFeedback()
        trace("yield")
        yield_result = processing.run(
            "fake_farm_data_generator:create_fake_yield_data",
            {
                "INPUT": str(fixture),
                "CROP_YEAR": 2025,
                "CROP_PROFILE": 0,
                "MIN_DRY_YIELD": 120.0,
                "MAX_DRY_YIELD": 240.0,
                "MIN_MOISTURE": 12.0,
                "MAX_MOISTURE": 25.0,
                "STANDARD_MOISTURE": 15.5,
                "SWATH_WIDTH": 100.0,
                "NOMINAL_SPEED": 4.0,
                "LOGGING_INTERVAL": 30.0,
                "HEADLAND_PASSES": 3,
                "HEADLAND_PENALTY": 10.0,
                "DIRECTION_MODE": 0,
                "HARVEST_MONTH_DAY": "10-15",
                "DATE_WINDOW": 14,
                "TIMEZONE": "America/Indianapolis",
                "VARIABILITY_LEVEL": 1,
                "CREATE_SURFACE": True,
                "SURFACE_GRID_SIZE": 250.0,
                "RANDOM_SEED": 11223,
                "OUTPUT_DIR": str(temporary_root),
            },
            feedback=yield_feedback,
        )
        yield_point_count, _yield_fields = assert_layer(
            yield_result["POINT_LAYER"],
            {
                "fake_data",
                "yield_id",
                "pass_id",
                "timestamp",
                "timezone",
                "crop_name",
                "crop_source",
                "dry_yield",
                "wet_yield",
                "yield_unit",
                "moisture_pct",
                "standard_moisture",
                "speed",
                "is_headland",
            },
        )
        yield_surface_count, _yield_surface_fields = assert_layer(
            yield_result["SURFACE_LAYER"],
            {
                "fake_data",
                "cell_id",
                "dry_yield",
                "wet_yield",
                "moisture_pct",
                "surface_method",
                "source_points",
            },
        )
        if set(text_attribute_values(yield_result["POINT_LAYER"], "timezone")) != {
            "America/Indianapolis"
        }:
            raise AssertionError("Yield timezone was not propagated")
        dry_yields = attribute_values(yield_result["POINT_LAYER"], "dry_yield")
        moistures = attribute_values(yield_result["POINT_LAYER"], "moisture_pct")
        if min(dry_yields) < 120.0 or max(dry_yields) > 240.0:
            raise AssertionError("Yield points exceeded configured dry-yield bounds")
        if min(moistures) < 12.0 or max(moistures) > 25.0:
            raise AssertionError("Yield points exceeded configured moisture bounds")
        if max(dry_yields) - min(dry_yields) < 10.0:
            raise AssertionError("Yield points did not vary materially")
        yield_layer = QgsVectorLayer(yield_result["POINT_LAYER"], "yield", "ogr")
        yield_features = list(yield_layer.getFeatures())
        if not any(bool(feature["is_headland"]) for feature in yield_features):
            raise AssertionError("Yield output did not create headland/end-row records")
        assert_perimeter_headlands(yield_result["POINT_LAYER"], "Yield")
        yield_manifest = json.loads(Path(yield_result["MANIFEST"]).read_text())
        if yield_manifest["status"] != "complete":
            raise AssertionError("Yield manifest did not finish complete")
        if yield_manifest["yield"]["crop_name"] != "Corn":
            raise AssertionError("Yield manifest did not retain crop profile")
        if yield_manifest["counts"]["yield_points"] != yield_point_count:
            raise AssertionError("Yield manifest point count does not match output")
        if yield_manifest["counts"]["surface_cells"] != yield_surface_count:
            raise AssertionError("Yield manifest surface count does not match output")
        if not any(
            message.startswith("Yield:")
            and "records created" in message
            and "elapsed" in message
            and "estimated remaining" in message
            for message in yield_feedback.info_messages
        ):
            raise AssertionError("Yield run did not report elapsed and remaining progress")

        trace("complete")
        complete_feedback = RecordingFeedback()
        complete_result = processing.run(
            "fake_farm_data_generator:create_complete_fake_farm_dataset",
            {
                "INPUT": str(fixture),
                "FIELD_ID_FIELD": "field_name",
                "YEARS": "2025",
                "TIMEZONE": "America/Indianapolis",
                "CREATE_SOIL": True,
                "SOIL_SETTINGS_JSON": json.dumps(
                    {
                        "placement": "Random",
                        "sample_density": 10,
                        "variability_level": "High",
                        "unattributed": True,
                        "create_surface": False,
                    }
                ),
                "CREATE_PLANTING": False,
                "CREATE_APPLICATIONS": True,
                "CREATE_YIELD": False,
                "APPLICATION_OPERATIONS_JSON": json.dumps(
                    [
                        {
                            "year": 2025,
                            "operation_id": "PRE_001",
                            "operation_type": "Dry Fertilizer",
                            "product_name": "Fake Dry Product",
                            "rate_mode": "Flat Rate",
                            "target_rate": 150,
                            "min_rate": 120,
                            "max_rate": 180,
                            "rate_unit": "lb/acre",
                        },
                        {
                            "year": "all",
                            "operation_id": "POST_001",
                            "operation_type": "Chemical Spraying",
                            "product_name": "Fake Spray Product",
                            "rate_mode": "Variable Rate",
                            "target_rate": 15,
                            "min_rate": 10,
                            "max_rate": 20,
                            "rate_unit": "gal/acre",
                        },
                    ]
                ),
                "CROP_PROFILE": 0,
                "OUTPUT_FORMATS": [0, 1, 2, 3, 4],
                "REVIEW_MAX_FEATURES": 100,
                "RANDOM_SEED": 44556,
                "OUTPUT_DIR": str(temporary_root),
            },
            feedback=complete_feedback,
        )
        complete_manifest = json.loads(Path(complete_result["MANIFEST"]).read_text())
        if complete_manifest["status"] != "complete":
            raise AssertionError("Complete-run manifest did not finish complete")
        overall_markers = [
            message
            for message in complete_feedback.info_messages
            if message.startswith("FFDG_OVERALL_PROGRESS|")
        ]
        if not overall_markers or not overall_markers[-1].startswith(
            "FFDG_OVERALL_PROGRESS|100|"
        ):
            raise AssertionError("Complete run did not emit finalized overall progress")
        if complete_manifest.get("timezone") != "America/Indianapolis":
            raise AssertionError("Complete-run timezone was not retained")
        if complete_manifest.get("review_max_features") != 100:
            raise AssertionError("Complete-run manifest did not retain the review feature limit")
        if (
            complete_manifest.get("field_mapping", {}).get("field_id") != "field_name"
            or {
                item["field_id"]
                for item in complete_manifest.get("field_identities", {}).values()
            }
            != {"West Field", "East Field"}
        ):
            raise AssertionError("Complete run did not retain mapped field identities")
        if (
            complete_manifest.get("estimates", {}).get("application_points", 0) <= 0
            or complete_manifest.get("estimates", {}).get("application_surface_cells", 0) <= 0
            or complete_manifest.get("estimates", {}).get("total_records", 0) <= 0
        ):
            raise AssertionError("Complete-run manifest did not retain its preflight estimate")
        if len(complete_manifest["components"]) != 3:
            raise AssertionError("Complete run did not retain soil and both configured operations")
        component_names = {item["name"] for item in complete_manifest["components"]}
        if component_names != {
            "soil",
            "applications_2025_PRE_001",
            "applications_2025_POST_001",
        }:
            raise AssertionError(f"Complete run retained the wrong components: {component_names}")
        complete_folder = Path(complete_result["OUTPUT_FOLDER"])
        yearly_relative = complete_manifest.get("yearly_geopackages", {}).get("2025")
        if yearly_relative != "2025/fake_farm_data_2025.gpkg":
            raise AssertionError("Complete run did not register its yearly GeoPackage")
        yearly_path = complete_folder / yearly_relative
        public_geopackages = [
            relative
            for relative in complete_manifest["outputs"]
            if Path(relative).suffix.lower() == ".gpkg"
        ]
        if public_geopackages != [yearly_relative]:
            raise AssertionError(
                f"Complete run did not expose exactly one GeoPackage for 2025: {public_geopackages}"
            )
        if list(yearly_path.parent.glob("*.gpkg")) != [yearly_path]:
            raise AssertionError(
                "The public year folder contains component GeoPackages in addition to the canonical package"
            )
        with closing(sqlite3.connect(yearly_path)) as connection:
            yearly_layers = {
                row[0]
                for row in connection.execute(
                    "SELECT table_name FROM gpkg_contents"
                )
            }
        expected_yearly_layers = {
            "fake_field_boundaries",
            "fake_soil_tests_2025",
            "fake_applications_2025",
            "fake_application_surface_2025",
            "ffdg_run_metadata",
        }
        if not expected_yearly_layers <= yearly_layers:
            raise AssertionError(
                f"Yearly GeoPackage is missing layers: {sorted(expected_yearly_layers - yearly_layers)}"
            )
        boundary_uri = f"{yearly_path}|layername=fake_field_boundaries"
        boundary_count, _boundary_fields = assert_layer(
            boundary_uri,
            {
                "fake_data",
                "fake_warning",
                "field_id",
                "field_name",
                "area_acres",
                "area_hectares",
                "boundary_source",
            },
        )
        boundary_layer = QgsVectorLayer(boundary_uri, "boundaries", "ogr")
        if (
            boundary_count != 2
            or {str(feature["field_id"]) for feature in boundary_layer.getFeatures()}
            != {"West Field", "East Field"}
            or complete_manifest.get("counts", {}).get("field_boundaries") != 2
        ):
            raise AssertionError("Complete run did not retain normalized field boundaries")
        del boundary_layer
        complete_soil_path = f"{yearly_path}|layername=fake_soil_tests_2025"
        complete_soil_layer = QgsVectorLayer(
            str(complete_soil_path), "complete_soil_identity", "ogr"
        )
        if {
            str(feature["field_id"]) for feature in complete_soil_layer.getFeatures()
        } != {"West Field", "East Field"}:
            raise AssertionError("Mapped identities did not reach complete-run soil output")
        del complete_soil_layer
        application_uri = f"{yearly_path}|layername=fake_applications_2025"
        if set(text_attribute_values(application_uri, "operation_id")) != {
            "PRE_001",
            "POST_001",
        }:
            raise AssertionError(
                "Consolidated application layer did not retain both operations"
            )
        archived_sources = complete_manifest.get("component_source_outputs", [])
        if not archived_sources or any(
            not (complete_folder / relative).is_file() for relative in archived_sources
        ):
            raise AssertionError("Complete run did not archive its component GeoPackages")
        for relative_output in complete_manifest["outputs"]:
            if not (complete_folder / relative_output).is_file():
                raise AssertionError(
                    f"Complete-run manifest output does not exist: {relative_output}"
                )
        saved_recipe = json.loads(Path(complete_result["RECIPE"]).read_text())
        if (
            saved_recipe["master_seed"] != 44556
            or saved_recipe["years"] != [2025]
            or saved_recipe.get("timezone") != "America/Indianapolis"
            or saved_recipe.get("review_max_features") != 100
            or saved_recipe.get("fake_warning")
            != "FAKE DATA - NOT FOR AGRONOMIC DECISIONS"
        ):
            raise AssertionError("Complete-run recipe did not preserve seed and years")
        if len(saved_recipe.get("application_operations", [])) != 2:
            raise AssertionError("Complete-run recipe did not preserve application operations")
        if (
            saved_recipe.get("soil_settings", {}).get("placement") != "Random"
            or not saved_recipe.get("soil_settings", {}).get("unattributed")
            or saved_recipe.get("soil_settings", {}).get("create_surface")
        ):
            raise AssertionError("Complete-run recipe did not preserve soil settings")
        if saved_recipe.get("estimates") != complete_manifest.get("estimates"):
            raise AssertionError("Recipe and manifest preflight estimates do not match")
        loaded_run_recipe_dialog = CompleteDatasetDialog(None)
        loaded_run_recipe_dialog._apply_dialog_recipe(saved_recipe)
        if (
            loaded_run_recipe_dialog.years.text() != "2025"
            or not loaded_run_recipe_dialog.create_soil.isChecked()
            or loaded_run_recipe_dialog.create_planting.isChecked()
            or not loaded_run_recipe_dialog.create_applications.isChecked()
            or loaded_run_recipe_dialog.create_yield.isChecked()
            or loaded_run_recipe_dialog._soil_settings()["placement"] != "Random"
            or loaded_run_recipe_dialog.application_table.rowCount() != 2
            or loaded_run_recipe_dialog._field_mapping()["field_id"] != "field_name"
            or loaded_run_recipe_dialog._timezone_text() != "America/Indianapolis"
            or loaded_run_recipe_dialog.review_max_features.value() != 100
        ):
            raise AssertionError("Generated run recipe could not be reloaded into the dialog")
        loaded_run_recipe_dialog.close()
        loaded_run_recipe_dialog.deleteLater()
        app.processEvents()
        del loaded_run_recipe_dialog
        component_operations = {
            json.loads(path.read_text())["application"]["operation_id"]
            for path in (complete_folder / "component_manifests").glob("applications_*.json")
        }
        if component_operations != {"PRE_001", "POST_001"}:
            raise AssertionError(
                f"Component manifests lost application identity: {component_operations}"
            )
        application_component_manifests = [
            json.loads(path.read_text())
            for path in (complete_folder / "component_manifests").glob("applications_*.json")
        ]
        if any(
            item.get("timezone") != "America/Indianapolis"
            for item in application_component_manifests
        ):
            raise AssertionError("Complete-run timezone did not reach application children")
        review_html = (complete_folder / "fake_farm_data_review.html").read_text(
            encoding="utf-8"
        )
        for required_review_text in (
            "FAKE DATA - NOT FOR AGRONOMIC DECISIONS",
            'id="leftSelect"',
            'id="rightSelect"',
            'id="swipe"',
            'id="handle"',
            'id="fieldFilter"',
            'id="yearFilter"',
            'id="dataTypeFilter"',
            'id="operationFilter"',
            'id="leftAttribute"',
            'id="rightAttribute"',
            'id="leftRamp"',
            'id="compareToggle"',
            "fake_farm_data_review_data/static/fake_farm_data_generator.png",
            "function zoomToField(fieldId)",
            "rightChooser.hidden=!enabled",
            "selectableLayers=layers.filter",
            "function refreshBoundaries()",
            "setCompare(false)",
            "fake_farm_data_review_data/static/leaflet.js",
            "fake_farm_data_review_data/layers.js",
        ):
            if required_review_text not in review_html:
                raise AssertionError(
                    f"Complete HTML review is missing: {required_review_text}"
                )
        for removed_review_text in (
            "Run manifest</a>",
            "Run recipe</a>",
            "Generated files (",
            "All fields",
            'id="compareToggle" type="checkbox" checked',
        ):
            if removed_review_text in review_html:
                raise AssertionError(
                    f"Complete HTML review retained removed UI: {removed_review_text}"
                )
        review_data = (complete_folder / "fake_farm_data_review_data" / "layers.js").read_text(
            encoding="utf-8"
        )
        if (
            "fake_applications_2025" not in review_data
            or "fake_field_boundaries" not in review_data
            or "FeatureCollection" not in review_data
            or '"numeric_attributes"' not in review_data
            or '"operation_id"' not in review_data
        ):
            raise AssertionError("Complete HTML review data is missing generated layers")
        review_prefix = "window.FFDG_LAYERS = "
        review_layers = json.loads(
            review_data.removeprefix(review_prefix).strip().removesuffix(";")
        )
        soil_review_layers = [
            item for item in review_layers if item["name"].startswith("fake_soil_tests_")
        ]
        if not soil_review_layers or any(
            item["displayed"] != item["total"] or item["review_sampling"] != "all"
            for item in soil_review_layers
        ):
            raise AssertionError("Portable review did not include every soil-test point")
        application_review_layers = [
            item for item in review_layers if item["name"] == "fake_applications_2025"
        ]
        if not application_review_layers or not any(
            item["total"] > 100
            and item["displayed"] <= 100
            and item["displayed"] < item["total"]
            and item["review_sampling"] == "deterministic_interval"
            for item in application_review_layers
        ):
            raise AssertionError("Portable review did not apply its high-volume layer limit")
        for static_name in ("leaflet.js", "leaflet.css", "LEAFLET_LICENSE.txt"):
            if not (
                complete_folder
                / "fake_farm_data_review_data"
                / "static"
                / static_name
            ).is_file():
                raise AssertionError(f"Portable review is missing local asset: {static_name}")
        if not (
            complete_folder
            / "fake_farm_data_review_data"
            / "static"
            / "fake_farm_data_generator.png"
        ).is_file():
            raise AssertionError("Portable review is missing its bundled logo")
        output_suffixes = {Path(relative).suffix.lower() for relative in complete_manifest["outputs"]}
        if not {".gpkg", ".shp", ".geojson", ".csv", ".tif"} <= output_suffixes:
            raise AssertionError(
                f"Complete run did not create every selected vector format: {output_suffixes}"
            )
        if "field_name_map.json" not in complete_manifest["outputs"]:
            raise AssertionError("Shapefile export did not create the field-name map")
        for suffix in (".shp", ".geojson"):
            exported_path = next(
                complete_folder / relative
                for relative in complete_manifest["outputs"]
                if Path(relative).suffix.lower() == suffix
            )
            exported_layer = QgsVectorLayer(str(exported_path), exported_path.stem, "ogr")
            if not exported_layer.isValid() or exported_layer.featureCount() <= 0:
                raise AssertionError(f"Selected export is not a valid vector layer: {exported_path}")
            del exported_layer
        raster_path = next(
            complete_folder / relative
            for relative in complete_manifest["outputs"]
            if Path(relative).suffix.lower() == ".tif"
        )
        raster_layer = QgsRasterLayer(str(raster_path), raster_path.stem)
        if not raster_layer.isValid() or raster_layer.width() <= 0 or raster_layer.height() <= 0:
            raise AssertionError(f"GeoTIFF derivative is invalid: {raster_path}")
        del raster_layer

        # Exercise the API-driven crop table without relying on network state.
        automatic_crop_dialog = CompleteDatasetDialog(None)
        automatic_crop_dialog._set_boundary_layers([review_layer])
        automatic_crop_dialog._set_years("2024")
        complete_dialog_module.suggest_api_field_year_assignments = fake_api_crops
        try:
            if not automatic_crop_dialog._refresh_crop_review():
                raise AssertionError("API crop table could not be populated")
        finally:
            complete_dialog_module.suggest_api_field_year_assignments = original_api_crops
        if automatic_crop_dialog.crop_review_table.rowCount() != 2 or any(
            automatic_crop_dialog.crop_review_table.item(row, 4).text()
            != "croplandcros"
            or automatic_crop_dialog.crop_review_table.item(row, 5).text()
            != "accepted"
            for row in range(automatic_crop_dialog.crop_review_table.rowCount())
        ):
            raise AssertionError("API crop table lost USDA source or status")
        if len(json.loads(automatic_crop_dialog._crop_assignments_json(True))) != 2:
            raise AssertionError("API crop table did not retain both field assignments")
        automatic_crop_dialog.close()
        automatic_crop_dialog.deleteLater()
        app.processEvents()
        del automatic_crop_dialog

        inferred_payload = json.dumps(
            {
                f"Field_{field_index:03d}:2025": CropAssignment(
                    crop_name="Soybeans",
                    crop_code=None,
                    crop_pct=0.0,
                    crop_source="rotation_inference",
                    crop_source_year=2024,
                    crop_resolution=30.0,
                    crop_lookup_at="2026-08-05T00:00:00-04:00",
                    crop_overridden=False,
                    cdl_class_name=None,
                    status="inferred_rotation",
                    review_required=False,
                    valid_agricultural_pixels=0,
                    total_pixels=0,
                ).to_dict()
                for field_index in (1, 2)
            }
        )
        trace("automatic-complete")
        automatic_complete = processing.run(
            "fake_farm_data_generator:create_complete_fake_farm_dataset",
            {
                "INPUT": str(fixture),
                "YEARS": "2025",
                "CREATE_SOIL": False,
                "CREATE_PLANTING": True,
                "PLANTING_SETTINGS_JSON": json.dumps(
                    {
                        "point_output": "Planter Center",
                        "logging_interval": 5,
                        "direction_mode": "Manual",
                        "manual_bearing": 87,
                        "create_surface": False,
                        "surface_attributes": [],
                    }
                ),
                "CREATE_APPLICATIONS": False,
                "CREATE_YIELD": True,
                "YIELD_SETTINGS_JSON": json.dumps(
                    {
                        "swath_width": 35,
                        "nominal_speed": 5,
                        "logging_interval": 2,
                        "headland_penalty": 15,
                        "direction_mode": "Manual",
                        "manual_bearing": 91,
                        "surface_grid_size": 250,
                        "profile_overrides": {
                            "Soybeans": {
                                "min_yield": 45,
                                "max_yield": 46,
                                "min_moisture": 11,
                                "max_moisture": 16,
                                "standard_moisture": 13,
                            }
                        },
                    }
                ),
                "CROP_LOOKUP_MODE": 1,
                "CROP_PROFILE": 0,
                "CROP_ASSIGNMENTS_JSON": inferred_payload,
                "RANDOM_SEED": 44557,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        automatic_manifest = json.loads(
            Path(automatic_complete["MANIFEST"]).read_text()
        )
        assignments = automatic_manifest["crop_assignments"]
        if set(assignments) != {"Field_001:2025", "Field_002:2025"}:
            raise AssertionError("Automatic complete run did not resolve every field-year")
        if any(
            item["crop_name"] != "Soybeans"
            or item["crop_code"] is not None
            or item["crop_source"] != "rotation_inference"
            or item["review_required"]
            for item in assignments.values()
        ):
            raise AssertionError("Rotation-inferred assignments were not accepted as soybeans")
        if len(automatic_manifest["components"]) != 4:
            raise AssertionError(
                "Automatic complete run did not create planting and yield per field"
            )
        if (
            automatic_manifest.get("planting_settings", {}).get("point_output")
            != "Planter Center"
            or automatic_manifest.get("planting_settings", {}).get("manual_bearing") != 87
            or automatic_manifest.get("yield_settings", {}).get("swath_width") != 35
            or automatic_manifest.get("yield_settings", {}).get("manual_bearing") != 91
            or automatic_manifest.get("yield_settings", {})
            .get("profile_overrides", {})
            .get("Soybeans", {})
            .get("max_yield")
            != 46
        ):
            raise AssertionError("Complete run did not retain planting/yield settings")
        automatic_component_folder = Path(automatic_complete["OUTPUT_FOLDER"]) / "component_manifests"
        planting_component = json.loads(
            next(automatic_component_folder.glob("planting_*.json")).read_text()
        )
        yield_component = json.loads(
            next(automatic_component_folder.glob("yield_*.json")).read_text()
        )
        if (
            planting_component["planting"]["direction_mode"] != "Manual"
            or planting_component["planting"]["point_output"] != "Planter Center"
            or planting_component["planting"]["target_population_seeds_per_acre"] != 140000
            or yield_component["yield"]["swath_width_feet"] != 35
            or yield_component["yield"]["headland_penalty_percent"] != 15
        ):
            raise AssertionError("Child generators did not receive complete-run settings")
        if automatic_manifest.get("cdl_cache_directory"):
            raise AssertionError("API-provided complete run unexpectedly retained a cache directory")
        automatic_folder = Path(automatic_complete["OUTPUT_FOLDER"])
        automatic_yearly_path = automatic_folder / automatic_manifest[
            "yearly_geopackages"
        ]["2025"]
        yield_layer = QgsVectorLayer(
            f"{automatic_yearly_path}|layername=fake_yield_points_2025",
            "automatic_yield",
            "ogr",
        )
        if not yield_layer.isValid() or yield_layer.featureCount() <= 0:
            raise AssertionError("Consolidated automatic yield layer is invalid")
        yield_features = list(yield_layer.getFeatures())
        if (
            {str(feature["field_id"]) for feature in yield_features}
            != {"Field_001", "Field_002"}
            or any(
                feature["crop_name"] != "Soybeans"
                or feature["crop_source"] != "rotation_inference"
                or not 45 <= float(feature["dry_yield"]) <= 46
                or not 11 <= float(feature["moisture_pct"]) <= 16
                for feature in yield_features
            )
        ):
            raise AssertionError(
                "Consolidated yield output did not carry both fields and CDL provenance"
            )
        del yield_layer

        trace("metric-soil")
        metric_soil = processing.run(
            "fake_farm_data_generator:create_fake_soil_test_data",
            {
                "INPUT": str(fixture),
                "UNIT_SYSTEM": 1,
                "FIRST_YEAR": 2025,
                "FINAL_YEAR": "2025",
                "SAMPLE_DENSITY": 1.011714,
                "P_UNIT": 1,
                "K_UNIT": 1,
                "CREATE_SURFACE": False,
                "CREATE_REVIEW": False,
                "RANDOM_SEED": 55001,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        metric_soil_path = metric_soil["POINT_LAYERS"].split(";")[0]
        metric_layer = QgsVectorLayer(metric_soil_path, "metric_soil", "ogr")
        metric_feature = next(metric_layer.getFeatures())
        if (
            metric_feature["unit_system"] != "Metric"
            or metric_feature["density_unit"] != "ha/point"
            or metric_feature["p_unit"] != "kg/ha"
            or metric_feature["k_unit"] != "kg/ha"
        ):
            raise AssertionError("Metric soil units were not propagated")
        del metric_layer

        trace("metric-planting")
        metric_planting = processing.run(
            "fake_farm_data_generator:create_fake_planting_data",
            {
                "INPUT": str(fixture),
                "UNIT_SYSTEM": 1,
                "CROP_YEAR": 2025,
                "POINT_OUTPUT": 0,
                "PLANTER_WIDTH": 12.192,
                "ROW_SPACING": 76.2,
                "TARGET_POPULATION": 79073.7,
                "MIN_POPULATION": 69189.5,
                "MAX_POPULATION": 88957.9,
                "SEED_DEPTH": 5.08,
                "NOMINAL_SPEED": 8.04672,
                "HEADLAND_PASSES": 2,
                "CREATE_SURFACE": False,
                "CREATE_REVIEW": False,
                "RANDOM_SEED": 55002,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        metric_layer = QgsVectorLayer(metric_planting["CENTER_LAYER"], "metric_planting", "ogr")
        metric_feature = next(metric_layer.getFeatures())
        if (
            metric_feature["unit_system"] != "Metric"
            or metric_feature["speed_unit"] != "km/h"
            or metric_feature["population_unit"] != "seeds/ha"
            or metric_feature["seed_spacing_unit"] != "cm"
            or metric_feature["distance_unit"] != "m"
        ):
            raise AssertionError("Metric planting units were not propagated")
        del metric_layer

        trace("metric-application")
        metric_application = processing.run(
            "fake_farm_data_generator:create_fake_as_applied_data",
            {
                "INPUT": str(fixture),
                "UNIT_SYSTEM": 1,
                "CROP_YEAR": 2025,
                "EQUIPMENT_WIDTH": 18.288,
                "NOMINAL_SPEED": 16.09344,
                "HEADLAND_PASSES": 2,
                "CREATE_SURFACE": False,
                "CREATE_REVIEW": False,
                "RANDOM_SEED": 55003,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        metric_layer = QgsVectorLayer(metric_application["POINT_LAYER"], "metric_application", "ogr")
        metric_feature = next(metric_layer.getFeatures())
        if (
            metric_feature["unit_system"] != "Metric"
            or metric_feature["speed_unit"] != "km/h"
            or metric_feature["distance_unit"] != "m"
            or metric_feature["rate_unit"] != "kg/ha"
        ):
            raise AssertionError("Metric application units were not propagated")
        del metric_layer

        trace("metric-yield")
        metric_yield = processing.run(
            "fake_farm_data_generator:create_fake_yield_data",
            {
                "INPUT": str(fixture),
                "UNIT_SYSTEM": 1,
                "CROP_YEAR": 2025,
                "CROP_PROFILE": 0,
                "MIN_DRY_YIELD": 7.53245,
                "MAX_DRY_YIELD": 15.0649,
                "SWATH_WIDTH": 9.144,
                "NOMINAL_SPEED": 6.437376,
                "HEADLAND_PASSES": 3,
                "CREATE_SURFACE": False,
                "CREATE_REVIEW": False,
                "RANDOM_SEED": 55004,
                "OUTPUT_DIR": str(temporary_root),
            },
        )
        metric_layer = QgsVectorLayer(metric_yield["POINT_LAYER"], "metric_yield", "ogr")
        metric_feature = next(metric_layer.getFeatures())
        if (
            metric_feature["unit_system"] != "Metric"
            or metric_feature["speed_unit"] != "km/h"
            or metric_feature["distance_unit"] != "m"
            or metric_feature["yield_unit"] != "t/ha"
        ):
            raise AssertionError("Metric yield units were not propagated")
        del metric_layer

        trace("complete-ok")
        print(
            "QGIS_SMOKE_OK "
            f"grid_points={point_count} kriging_surface_cells={surface_count} "
            f"random_unattributed_points={random_count} "
            f"planting_center_points={planting_center_count} "
            f"planting_row_points={planting_row_count} "
            f"planting_surface_cells={planting_surface_count} "
            f"automatic_center_points={automatic_center_count} "
            f"application_points={application_point_count} "
            f"application_surface_cells={application_surface_count} "
            f"yield_points={yield_point_count} yield_surface_cells={yield_surface_count} "
            f"complete_components={len(complete_manifest['components'])} "
            f"automatic_crop_assignments={len(assignments)} "
            f"canceled_status={canceled_manifest['status']} "
            f"yield_progress_messages={len(yield_feedback.info_messages)} "
            "metric_generators=4 "
            f"algorithms={len(actual)}",
            flush=True,
        )
    finally:
        from qgis.core import QgsProject

        QgsProject.instance().clear()
        if provider is not None:
            QgsApplication.processingRegistry().removeProvider(provider)
            provider = None
        gc.collect()
        app.exitQgis()
        if os.environ.get("FAKE_FARM_KEEP_TEMP"):
            print(f"QGIS_SMOKE_OUTPUT={temporary_root}")
        else:
            shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    main()
