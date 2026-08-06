# SPDX-License-Identifier: GPL-3.0-or-later
"""Orchestrate the four fake-data generators into one multi-year run."""

from __future__ import annotations

import json
import random
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsDistanceArea,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputString,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterField,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..core.generation import (
    FAKE_WARNING,
    feature_field_identity,
    normalize_timezone_label,
    parse_years,
    stable_seed,
)
from ..core.application_operations import (
    normalize_application_operations,
    operation_to_processing_parameters,
)
from ..core.units import UNIT_SYSTEM_OPTIONS, metric_yield_profile, unit_system
from ..core.point_estimator import estimate_complete_records
from ..core.preflight_review import runtime_estimate_text
from ..core.gpkg_metadata import write_gpkg_run_metadata
from ..core.gpkg_consolidation import consolidate_complete_run_geopackages
from ..core.review_settings import (
    DEFAULT_REVIEW_MAX_FEATURES,
    MAX_REVIEW_MAX_FEATURES,
    MIN_REVIEW_MAX_FEATURES,
    normalize_review_max_features,
)
from ..core.complete_settings import (
    default_planting_settings,
    default_soil_settings,
    default_yield_settings,
    normalize_planting_settings,
    normalize_soil_settings,
    normalize_yield_settings,
    planting_processing_parameters,
    resolve_soil_schedule,
    soil_processing_parameters,
    yield_processing_parameters,
)
from ..crops.manager import parse_assignment_payload, resolve_field_year_assignments
from ..exporters import OUTPUT_FORMAT_OPTIONS, export_vector_derivatives
from ..review.builder import build_portable_review
from .applications import CreateFakeApplicationsAlgorithm
from .planting import CreateFakePlantingAlgorithm
from .yield_data import CreateFakeYieldAlgorithm


class _ScaledComponentFeedback(QgsProcessingFeedback):
    """Map a child algorithm's progress into one overall complete-run range."""

    def __init__(self, parent, start_percent, end_percent, label):
        super().__init__()
        self.parent = parent
        self.start_percent = float(start_percent)
        self.end_percent = float(end_percent)
        self.label = str(label)
        self._last_marker = -1

    def isCanceled(self):
        return bool(self.parent and self.parent.isCanceled())

    def setProgress(self, progress):
        child = max(0.0, min(100.0, float(progress)))
        overall = self.start_percent + (
            (self.end_percent - self.start_percent) * child / 100.0
        )
        if self.parent is not None:
            self.parent.setProgress(overall)
            marker = int(overall)
            if marker != self._last_marker:
                self.parent.pushInfo(
                    f"FFDG_OVERALL_PROGRESS|{marker}|Creating {self.label}"
                )
                self._last_marker = marker

    def setProgressText(self, text):
        if self.parent is not None:
            self.parent.setProgressText(str(text))

    def pushInfo(self, info):
        if self.parent is not None:
            self.parent.pushInfo(str(info))

    def pushWarning(self, warning):
        if self.parent is not None:
            self.parent.pushWarning(str(warning))

    def reportError(self, error, fatalError=False):
        if self.parent is not None:
            self.parent.reportError(str(error), fatalError)

    def pushDebugInfo(self, info):
        if self.parent is not None:
            self.parent.pushDebugInfo(str(info))

    def pushCommandInfo(self, info):
        if self.parent is not None:
            self.parent.pushCommandInfo(str(info))

    def pushConsoleInfo(self, info):
        if self.parent is not None:
            self.parent.pushConsoleInfo(str(info))


class CreateCompleteFakeFarmDatasetAlgorithm(QgsProcessingAlgorithm):
    INPUT = "INPUT"
    FIELD_ID_FIELD = "FIELD_ID_FIELD"
    FIELD_NAME_FIELD = "FIELD_NAME_FIELD"
    FARM_NAME_FIELD = "FARM_NAME_FIELD"
    GROWER_NAME_FIELD = "GROWER_NAME_FIELD"
    UNIT_SYSTEM = "UNIT_SYSTEM"
    YEARS = "YEARS"
    TIMEZONE = "TIMEZONE"
    CREATE_SOIL = "CREATE_SOIL"
    SOIL_SETTINGS_JSON = "SOIL_SETTINGS_JSON"
    CREATE_PLANTING = "CREATE_PLANTING"
    PLANTING_SETTINGS_JSON = "PLANTING_SETTINGS_JSON"
    CREATE_APPLICATIONS = "CREATE_APPLICATIONS"
    APPLICATION_OPERATIONS_JSON = "APPLICATION_OPERATIONS_JSON"
    CREATE_YIELD = "CREATE_YIELD"
    YIELD_SETTINGS_JSON = "YIELD_SETTINGS_JSON"
    SOIL_INTERVAL = "SOIL_INTERVAL"
    SOIL_FIRST_YEAR = "SOIL_FIRST_YEAR"
    SOIL_FINAL_YEAR = "SOIL_FINAL_YEAR"
    CROP_LOOKUP_MODE = "CROP_LOOKUP_MODE"
    CROP_PROFILE = "CROP_PROFILE"
    LOCAL_CDL_PATH = "LOCAL_CDL_PATH"
    CDL_CACHE_DIRECTORY = "CDL_CACHE_DIRECTORY"
    CROP_OVERRIDES_JSON = "CROP_OVERRIDES_JSON"
    CROP_ASSIGNMENTS_JSON = "CROP_ASSIGNMENTS_JSON"
    RANDOM_SEED = "RANDOM_SEED"
    OUTPUT_FORMATS = "OUTPUT_FORMATS"
    REVIEW_MAX_FEATURES = "REVIEW_MAX_FEATURES"
    OUTPUT_DIR = "OUTPUT_DIR"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    MANIFEST = "MANIFEST"
    RECIPE = "RECIPE"

    CROP_LOOKUP_OPTIONS = ["Manual profile", "Automatic CDL"]

    def tr(self, text):
        return QCoreApplication.translate("FakeFarmDataGenerator", text)

    def createInstance(self):
        return CreateCompleteFakeFarmDatasetAlgorithm()

    def createCustomParametersWidget(self, parent=None):
        """Open the complete tabbed builder instead of QGIS's long JSON form."""

        from ..complete_dialog import CompleteDatasetDialog

        return CompleteDatasetDialog(None, parent=parent)

    def name(self):
        return "create_complete_fake_farm_dataset"

    def displayName(self):
        return self.tr("Create Complete Fake Farm Dataset")

    def group(self):
        return self.tr("Fake Farm Data Generator")

    def groupId(self):
        return "fake_farm_data_generator"

    def shortHelpString(self):
        return self.tr(
            "Creates any selected combination of soil, planting, as-applied, and yield "
            "data for up to ten years in one consolidated run folder. This Processing "
            "orchestrator's custom dialog combines checked polygon layers, provides "
            "checkable crop years and a timezone selector, and pulls crops from the USDA "
            "CDL API on demand. Missing CDL years may be inferred from observed rotation "
            "with explicit provenance. All generator inputs are exposed as controls."
        )

    @staticmethod
    def _hidden(parameter):
        hidden = getattr(QgsProcessingParameterDefinition, "FlagHidden", None)
        if hidden is None:
            hidden = QgsProcessingParameterDefinition.Flag.FlagHidden
        parameter.setFlags(parameter.flags() | hidden)
        return parameter

    def initAlgorithm(self, config=None):
        current_year = datetime.now().year
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr("Field boundaries (selected features take precedence)"),
                [QgsProcessing.SourceType.TypeVectorPolygon],
            )
        )
        for name, label in (
            (self.FIELD_ID_FIELD, "Field ID column (optional; auto-detected when blank)"),
            (self.FIELD_NAME_FIELD, "Field name column (optional; auto-detected when blank)"),
            (self.FARM_NAME_FIELD, "Farm name column (optional; auto-detected when blank)"),
            (self.GROWER_NAME_FIELD, "Grower name column (optional; auto-detected when blank)"),
        ):
            self.addParameter(
                QgsProcessingParameterField(
                    name,
                    self.tr(label),
                    None,
                    self.INPUT,
                    QgsProcessingParameterField.DataType.Any,
                    False,
                    True,
                )
            )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.UNIT_SYSTEM, self.tr("Unit system"), UNIT_SYSTEM_OPTIONS, False, 0
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.YEARS,
                self.tr("Years (comma-separated years and inclusive ranges)"),
                str(current_year),
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TIMEZONE,
                self.tr("Timezone label for machine timestamps (optional)"),
                "",
                False,
                True,
            )
        )
        for name, label, default in (
            (self.CREATE_SOIL, "Create soil-test data", True),
            (self.CREATE_PLANTING, "Create planting data", True),
            (self.CREATE_APPLICATIONS, "Create as-applied data", True),
            (self.CREATE_YIELD, "Create yield data", True),
        ):
            self.addParameter(QgsProcessingParameterBoolean(name, self.tr(label), default))
        for name, label in (
            (self.SOIL_SETTINGS_JSON, "Internal soil settings"),
            (self.PLANTING_SETTINGS_JSON, "Internal planting settings"),
            (self.YIELD_SETTINGS_JSON, "Internal yield settings"),
        ):
            self.addParameter(
                self._hidden(
                    QgsProcessingParameterString(name, self.tr(label), "", True, True)
                )
            )
        self.addParameter(
            self._hidden(
                QgsProcessingParameterString(
                    self.APPLICATION_OPERATIONS_JSON,
                    self.tr("Internal application operations"),
                    "",
                    True,
                    True,
                )
            )
        )
        self.addParameter(
            self._hidden(
                QgsProcessingParameterString(
                    self.CROP_ASSIGNMENTS_JSON,
                    self.tr("Internal API crop assignments"),
                    "",
                    True,
                    True,
                )
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SOIL_INTERVAL,
                self.tr("Soil sampling interval (years)"),
                QgsProcessingParameterNumber.Type.Integer,
                3,
                False,
                1,
                10,
            )
        )
        for name, label in (
            (self.SOIL_FIRST_YEAR, "First soil sampling year (blank = first run year)"),
            (self.SOIL_FINAL_YEAR, "Final soil sampling year (blank = last run year)"),
        ):
            self.addParameter(
                QgsProcessingParameterString(
                    name,
                    self.tr(label),
                    "",
                    False,
                    True,
                )
            )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OUTPUT_FORMATS,
                self.tr("Output formats"),
                OUTPUT_FORMAT_OPTIONS,
                True,
                [0],
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.REVIEW_MAX_FEATURES,
                self.tr("Maximum displayed features per high-volume review layer"),
                QgsProcessingParameterNumber.Type.Integer,
                DEFAULT_REVIEW_MAX_FEATURES,
                False,
                MIN_REVIEW_MAX_FEATURES,
                MAX_REVIEW_MAX_FEATURES,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CROP_LOOKUP_MODE,
                self.tr("Crop assignment mode"),
                self.CROP_LOOKUP_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CROP_PROFILE,
                self.tr("Reviewed manual crop profile"),
                CreateFakeYieldAlgorithm.CROP_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.LOCAL_CDL_PATH,
                self.tr("Local CDL raster or directory (optional)"),
                "",
                False,
                True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.CDL_CACHE_DIRECTORY,
                self.tr("CDL cache directory (blank uses QGIS cache)"),
                "",
                False,
                True,
            )
        )
        self.addParameter(
            self._hidden(
                QgsProcessingParameterString(
                    self.CROP_OVERRIDES_JSON,
                    self.tr("Internal reviewed crop overrides"),
                    "",
                    True,
                    True,
                )
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.RANDOM_SEED,
                self.tr("Master random seed (0 = random)"),
                QgsProcessingParameterNumber.Type.Integer,
                0,
                False,
                0,
                2_147_483_647,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR, self.tr("Parent output directory")
            )
        )
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_FOLDER, "Complete run folder"))
        self.addOutput(QgsProcessingOutputString(self.MANIFEST, "Complete run manifest"))
        self.addOutput(QgsProcessingOutputString(self.RECIPE, "Saved run recipe"))

    @staticmethod
    def _copy_component(component_folder, run_folder, component_name, outputs):
        component_folder = Path(component_folder)
        manifest_path = component_folder / "run_manifest.json"
        component_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_destination = run_folder / "component_manifests"
        manifest_destination.mkdir(exist_ok=True)
        copied = []
        for relative_text in component_manifest.get("outputs", []):
            relative = Path(relative_text)
            source_path = component_folder / relative
            destination = run_folder / "component_sources" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = destination.with_name(
                    f"{destination.stem}_{component_name}{destination.suffix}"
                )
            shutil.copy2(source_path, destination)
            copied.append(str(destination.relative_to(run_folder)))
            outputs.append(str(destination.relative_to(run_folder)))
        manifest_copy = manifest_destination / f"{component_name}.json"
        shutil.copy2(manifest_path, manifest_copy)
        return component_manifest, copied

    @staticmethod
    def _selected_or_all(layer):
        if layer.selectedFeatureCount() > 0:
            return list(layer.selectedFeatures()), True
        return list(layer.getFeatures()), False

    @staticmethod
    def _single_field_layer(source, source_feature, field_id, identity):
        """Create an in-memory one-feature layer carrying the stable complete-run ID."""

        layer = QgsVectorLayer("MultiPolygon", field_id, "memory")
        if not layer.isValid():
            raise QgsProcessingException(f"Could not create temporary layer for {field_id}")
        layer.setCrs(source.crs())
        provider = layer.dataProvider()
        provider.addAttributes(list(source.fields()))
        existing_names = set(source.fields().names())
        for identity_name in ("field_id", "field_name", "farm_name", "grower_name"):
            if identity_name not in existing_names:
                provider.addAttributes([QgsField(identity_name, QVariant.String)])
        if "ffdg_field_id" not in source.fields().names():
            provider.addAttributes([QgsField("ffdg_field_id", QVariant.String)])
        layer.updateFields()
        feature = QgsFeature(layer.fields())
        geometry = QgsGeometry(source_feature.geometry())
        if QgsWkbTypes.geometryType(geometry.wkbType()) != QgsWkbTypes.GeometryType.PolygonGeometry:
            raise QgsProcessingException(f"{field_id} is not polygon geometry")
        if not QgsWkbTypes.isMultiType(geometry.wkbType()):
            geometry.convertToMultiType()
        feature.setGeometry(geometry)
        for field_name in source.fields().names():
            feature.setAttribute(field_name, source_feature.attribute(field_name))
        for identity_name, identity_value in identity.items():
            feature.setAttribute(identity_name, identity_value)
        feature.setAttribute("ffdg_field_id", field_id)
        if not provider.addFeature(feature):
            raise QgsProcessingException(f"Could not copy geometry for {field_id}")
        layer.updateExtents()
        return layer

    @staticmethod
    def _write_field_boundaries(
        path,
        source,
        features,
        field_identities,
        area_calculator,
        run_id,
        created_at,
        master_seed,
        unit_system_name,
    ):
        fields = QgsFields()
        for name, variant in (
            ("fake_data", QVariant.Bool),
            ("fake_warning", QVariant.String),
            ("generator_name", QVariant.String),
            ("generator_version", QVariant.String),
            ("run_id", QVariant.String),
            ("created_at", QVariant.String),
            ("master_seed", QVariant.Int),
            ("unit_system", QVariant.String),
            ("data_type", QVariant.String),
            ("field_id", QVariant.String),
            ("field_name", QVariant.String),
            ("farm_name", QVariant.String),
            ("grower_name", QVariant.String),
            ("crop_year", QVariant.Int),
            ("area_acres", QVariant.Double),
            ("area_hectares", QVariant.Double),
            ("boundary_source", QVariant.String),
        ):
            fields.append(QgsField(name, variant))
        writer = CreateFakePlantingAlgorithm._writer(
            path,
            fields,
            source.crs(),
            QgsWkbTypes.Type.MultiPolygon,
            "fake_field_boundaries",
        )
        count = 0
        for index, source_feature in enumerate(features, start=1):
            internal_id = f"Field_{index:03d}"
            identity = field_identities[internal_id]
            geometry = QgsGeometry(source_feature.geometry())
            if geometry.isEmpty():
                continue
            if not QgsWkbTypes.isMultiType(geometry.wkbType()):
                geometry.convertToMultiType()
            area_m2 = abs(area_calculator.measureArea(source_feature.geometry()))
            output_feature = QgsFeature(fields)
            output_feature.setGeometry(geometry)
            for name, value in {
                "fake_data": True,
                "fake_warning": FAKE_WARNING,
                "generator_name": "Fake Farm Data Generator",
                "generator_version": "1.0.1",
                "run_id": run_id,
                "created_at": created_at,
                "master_seed": master_seed,
                "unit_system": unit_system_name,
                "data_type": "field_boundary",
                **identity,
                "crop_year": 0,
                "area_acres": round(area_m2 / 4046.8564224, 4),
                "area_hectares": round(area_m2 / 10000.0, 4),
                "boundary_source": "user_provided",
            }.items():
                output_feature.setAttribute(name, value)
            if not writer.addFeature(output_feature):
                del writer
                raise QgsProcessingException(
                    f"Could not write normalized boundary for {identity['field_id']}"
                )
            count += 1
        del writer
        return count

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException("Invalid field-boundary layer")
        features, used_selection = self._selected_or_all(source)
        if not features:
            raise QgsProcessingException("No field features were supplied")
        if len(features) > 20:
            raise QgsProcessingException(
                f"Selected {len(features)} fields; the v1 limit is 20 fields"
            )
        if not source.crs().isValid():
            raise QgsProcessingException("Field-boundary layer has a missing or invalid CRS")
        field_mapping = {
            "field_id": self.parameterAsString(parameters, self.FIELD_ID_FIELD, context),
            "field_name": self.parameterAsString(parameters, self.FIELD_NAME_FIELD, context),
            "farm_name": self.parameterAsString(parameters, self.FARM_NAME_FIELD, context),
            "grower_name": self.parameterAsString(parameters, self.GROWER_NAME_FIELD, context),
        }
        source_field_names = set(source.fields().names())
        invalid_mappings = sorted(
            value
            for value in field_mapping.values()
            if value and value not in source_field_names
        )
        if invalid_mappings:
            raise QgsProcessingException(
                "Mapped identity column(s) do not exist: " + ", ".join(invalid_mappings)
            )
        field_identities = {
            f"Field_{index:03d}": feature_field_identity(feature, index, field_mapping)
            for index, feature in enumerate(features, start=1)
        }
        mapped_ids = [identity["field_id"] for identity in field_identities.values()]
        if len(set(mapped_ids)) != len(mapped_ids):
            raise QgsProcessingException("Mapped field IDs must be unique within a run")
        area_calculator = QgsDistanceArea()
        area_calculator.setSourceCrs(source.crs(), context.transformContext())
        area_calculator.setEllipsoid("WGS84")
        total_area_m2 = sum(
            abs(area_calculator.measureArea(feature.geometry()))
            for feature in features
            if feature.hasGeometry() and not feature.geometry().isEmpty()
        )
        total_area_acres = total_area_m2 / 4046.8564224
        total_area_hectares = total_area_m2 / 10000.0
        if total_area_m2 <= 0:
            raise QgsProcessingException("Selected field polygons have no measurable area")
        if total_area_acres > 5000.0 + 0.001:
            raise QgsProcessingException(
                f"Selected fields total {total_area_acres:,.1f} acres; the v1 limit is 5,000 acres"
            )
        unit_index = self.parameterAsEnum(parameters, self.UNIT_SYSTEM, context)
        units = unit_system(unit_index)
        try:
            years = parse_years(self.parameterAsString(parameters, self.YEARS, context))
            timezone_label = normalize_timezone_label(
                self.parameterAsString(parameters, self.TIMEZONE, context)
            )
        except (TypeError, ValueError) as error:
            raise QgsProcessingException(str(error)) from error
        enabled = {
            "soil": self.parameterAsBool(parameters, self.CREATE_SOIL, context),
            "planting": self.parameterAsBool(parameters, self.CREATE_PLANTING, context),
            "applications": self.parameterAsBool(parameters, self.CREATE_APPLICATIONS, context),
            "yield": self.parameterAsBool(parameters, self.CREATE_YIELD, context),
        }
        if not any(enabled.values()):
            raise QgsProcessingException("Select at least one data type to create")
        try:
            soil_settings = (
                normalize_soil_settings(
                    self.parameterAsString(parameters, self.SOIL_SETTINGS_JSON, context),
                    unit_index,
                )
                if enabled["soil"]
                else default_soil_settings(unit_index)
            )
            planting_settings = (
                normalize_planting_settings(
                    self.parameterAsString(parameters, self.PLANTING_SETTINGS_JSON, context),
                    unit_index,
                )
                if enabled["planting"]
                else default_planting_settings(unit_index)
            )
            yield_settings = (
                normalize_yield_settings(
                    self.parameterAsString(parameters, self.YIELD_SETTINGS_JSON, context),
                    unit_index,
                )
                if enabled["yield"]
                else default_yield_settings(unit_index)
            )
        except (TypeError, ValueError) as error:
            raise QgsProcessingException(str(error)) from error
        application_operations_json = self.parameterAsString(
            parameters, self.APPLICATION_OPERATIONS_JSON, context
        )
        application_operations = []
        if enabled["applications"]:
            try:
                application_operations = normalize_application_operations(
                    application_operations_json, years
                )
                for operation in application_operations:
                    if not operation["timezone"]:
                        operation["timezone"] = timezone_label
            except (TypeError, ValueError) as error:
                raise QgsProcessingException(str(error)) from error

            # Blank JSON retains the pre-v0.12 baseline behavior. Explicit JSON
            # values are already expressed in the selected top-level unit system.
            if units.metric and not application_operations_json.strip():
                for operation in application_operations:
                    operation.update(
                        {
                            "equipment_width": 18.288,
                            "nominal_speed": 16.09344,
                            "surface_grid_size": 9.144,
                        }
                    )
        soil_interval = self.parameterAsInt(parameters, self.SOIL_INTERVAL, context)
        try:
            soil_years = (
                resolve_soil_schedule(
                    years,
                    soil_interval,
                    self.parameterAsString(parameters, self.SOIL_FIRST_YEAR, context),
                    self.parameterAsString(parameters, self.SOIL_FINAL_YEAR, context),
                )
                if enabled["soil"]
                else []
            )
        except (TypeError, ValueError) as error:
            raise QgsProcessingException(str(error)) from error
        crop_index = self.parameterAsEnum(parameters, self.CROP_PROFILE, context)
        crop_name = CreateFakeYieldAlgorithm.CROP_OPTIONS[crop_index]
        crop_lookup_mode = self.CROP_LOOKUP_OPTIONS[
            self.parameterAsEnum(parameters, self.CROP_LOOKUP_MODE, context)
        ]
        local_cdl_path = self.parameterAsString(parameters, self.LOCAL_CDL_PATH, context)
        cache_directory = self.parameterAsString(
            parameters, self.CDL_CACHE_DIRECTORY, context
        )
        crop_overrides = self.parameterAsString(
            parameters, self.CROP_OVERRIDES_JSON, context
        )
        crop_assignments_payload = self.parameterAsString(
            parameters, self.CROP_ASSIGNMENTS_JSON, context
        )
        requested_seed = self.parameterAsInt(parameters, self.RANDOM_SEED, context)
        review_max_features = normalize_review_max_features(
            self.parameterAsInt(parameters, self.REVIEW_MAX_FEATURES, context)
        )
        output_formats = [
            OUTPUT_FORMAT_OPTIONS[index]
            for index in self.parameterAsEnums(parameters, self.OUTPUT_FORMATS, context)
        ]
        if not output_formats:
            output_formats = ["GeoPackage"]
        master_seed = requested_seed or random.SystemRandom().randint(1, 2_147_483_647)
        parent = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))
        if not parent.is_dir():
            raise QgsProcessingException(f"Output directory does not exist: {parent}")

        estimates = estimate_complete_records(
            total_area_m2,
            years,
            enabled,
            soil_interval,
            unit_index,
            application_operations,
            soil_settings,
            planting_settings,
            yield_settings,
            soil_years,
        )
        estimated_runtime = runtime_estimate_text(
            estimates, output_formats, review_max_features
        )
        feedback.pushInfo(
            f"Complete preflight estimate: {estimates['total_points']:,} points, "
            f"{estimates['total_surface_cells']:,} polygon-grid cells, "
            f"{estimates['total_records']:,} total records"
        )
        feedback.pushInfo(f"Estimated runtime: {estimated_runtime}")
        if estimates["total_records"] >= 100_000:
            feedback.pushWarning(
                "This run may take a while. QGIS must remain open until processing finishes."
            )

        crop_assignments = {}
        if enabled["planting"] or enabled["yield"]:
            try:
                crop_assignments = parse_assignment_payload(
                    crop_assignments_payload,
                    CreateFakeYieldAlgorithm.CROP_OPTIONS,
                )
                expected_assignments = {
                    (f"Field_{field_index:03d}", year)
                    for field_index in range(1, len(features) + 1)
                    for year in years
                }
                if crop_assignments:
                    missing_assignments = sorted(expected_assignments - set(crop_assignments))
                    if missing_assignments:
                        raise ValueError(
                            "API crop assignments are missing: "
                            + ", ".join(
                                f"{field_id} {year}"
                                for field_id, year in missing_assignments
                            )
                        )
                else:
                    crop_assignments = resolve_field_year_assignments(
                        features,
                        source.crs(),
                        context.transformContext(),
                        years,
                        crop_lookup_mode,
                        crop_name,
                        crop_overrides,
                        CreateFakeYieldAlgorithm.CROP_OPTIONS,
                        local_cdl_path,
                        cache_directory,
                        feedback,
                    )
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                raise QgsProcessingException(str(error)) from error

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_folder = parent / f"Fake_Farm_Data_{run_id}"
        run_folder.mkdir()
        manifest_path = run_folder / "run_manifest.json"
        recipe_path = run_folder / "run_recipe.json"
        recipe = {
            "schema_version": 1,
            "recipe_type": "fake_farm_data_generator_run",
            "fake_data": True,
            "fake_warning": FAKE_WARNING,
            "generator_name": "Fake Farm Data Generator",
            "generator_version": "1.0.1",
            "years": years,
            "field_count": len(features),
            "field_mapping": field_mapping,
            "field_identities": field_identities,
            "total_area_acres": round(total_area_acres, 4),
            "total_area_hectares": round(total_area_hectares, 4),
            "data_types": enabled,
            "soil_interval": soil_interval,
            "soil_first_year": soil_years[0] if soil_years else None,
            "soil_final_year": soil_years[-1] if soil_years else None,
            "soil_years": soil_years,
            "soil_settings": soil_settings,
            "planting_settings": planting_settings,
            "yield_settings": yield_settings,
            "application_operations": application_operations,
            "crop_profile": crop_name,
            "crop_lookup_mode": crop_lookup_mode,
            "local_cdl_path": local_cdl_path,
            "cdl_cache_directory": cache_directory,
            "crop_overrides_json": crop_overrides,
            "crop_assignments": {
                f"{field_id}:{year}": assignment.to_dict()
                for (field_id, year), assignment in crop_assignments.items()
            },
            "master_seed": master_seed,
            "unit_system": units.name,
            "timezone": timezone_label,
            "output_formats": output_formats,
            "review_max_features": review_max_features,
            "estimates": estimates,
            "estimated_runtime": estimated_runtime,
        }
        recipe_path.write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "status": "running",
            "fake_data": True,
            "fake_warning": FAKE_WARNING,
            "generator": "Fake Farm Data Generator 1.0.1",
            "run_id": run_id,
            "created_at": created_at,
            "master_seed": master_seed,
            "unit_system": units.name,
            "timezone": timezone_label,
            "years": years,
            "field_count": len(features),
            "field_mapping": field_mapping,
            "field_identities": field_identities,
            "total_area_acres": round(total_area_acres, 4),
            "total_area_hectares": round(total_area_hectares, 4),
            "data_types": enabled,
            "soil_interval": soil_interval,
            "soil_first_year": soil_years[0] if soil_years else None,
            "soil_final_year": soil_years[-1] if soil_years else None,
            "soil_years": soil_years,
            "application_operations": application_operations,
            "soil_settings": soil_settings,
            "planting_settings": planting_settings,
            "yield_settings": yield_settings,
            "crop_profile": crop_name,
            "crop_lookup_mode": crop_lookup_mode,
            "cdl_cache_directory": cache_directory,
            "crop_assignments": {
                f"{field_id}:{year}": assignment.to_dict()
                for (field_id, year), assignment in crop_assignments.items()
            },
            "used_selected_features": used_selection,
            "components": [],
            "outputs": ["run_recipe.json"],
            "output_formats": output_formats,
            "review_max_features": review_max_features,
            "counts": {},
            "estimates": estimates,
            "estimated_runtime": estimated_runtime,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        readme = run_folder / "README_FAKE_DATA.txt"
        readme.write_text(
            f"{FAKE_WARNING}\n\nGenerated by Fake Farm Data Generator 1.0.1.\n",
            encoding="utf-8",
        )
        manifest["outputs"].append(readme.name)

        try:
            boundary_path = run_folder / "component_sources" / "fake_field_boundaries.gpkg"
            boundary_path.parent.mkdir(parents=True, exist_ok=True)
            boundary_count = self._write_field_boundaries(
                boundary_path,
                source,
                features,
                field_identities,
                area_calculator,
                run_id,
                created_at,
                master_seed,
                units.name,
            )
            manifest["counts"]["field_boundaries"] = boundary_count
            manifest["outputs"].append(boundary_path.relative_to(run_folder).as_posix())
            write_gpkg_run_metadata([boundary_path], manifest)
            normalized_source = QgsVectorLayer(
                str(boundary_path), "fake_field_boundaries", "ogr"
            )
            if not normalized_source.isValid():
                raise QgsProcessingException(
                    "Could not reopen normalized field boundaries for child generators"
                )
            with tempfile.TemporaryDirectory(prefix="ffdg_complete_") as temporary:
                temporary_path = Path(temporary)
                tasks = []
                field_layers = {
                    f"Field_{field_index:03d}": self._single_field_layer(
                        source,
                        feature,
                        f"Field_{field_index:03d}",
                        field_identities[f"Field_{field_index:03d}"],
                    )
                    for field_index, feature in enumerate(features, start=1)
                }
                if enabled["soil"]:
                    tasks.append(
                        (
                            "soil",
                            "fake_farm_data_generator:create_fake_soil_test_data",
                            {
                                "INPUT": normalized_source,
                                "UNIT_SYSTEM": unit_index,
                                "FIRST_YEAR": soil_years[0],
                                "INTERVAL": soil_interval,
                                "FINAL_YEAR": str(soil_years[-1]),
                                "RANDOM_SEED": stable_seed(master_seed, "soil"),
                                "CREATE_REVIEW": False,
                                "OUTPUT_DIR": str(temporary_path),
                                **soil_processing_parameters(soil_settings),
                            },
                        )
                    )
                for year in years:
                    if enabled["planting"]:
                        for field_id, field_layer in field_layers.items():
                            assignment = crop_assignments[(field_id, year)]
                            crop_planting_settings = dict(planting_settings)
                            crop_planting_settings.update(
                                planting_settings.get("crop_profiles", {}).get(
                                    assignment.crop_name, {}
                                )
                            )
                            tasks.append(
                                (
                                    f"planting_{field_id}_{year}",
                                    "fake_farm_data_generator:create_fake_planting_data",
                                    {
                                        "INPUT": field_layer,
                                        "UNIT_SYSTEM": unit_index,
                                        "CROP_YEAR": year,
                                        "CROP_NAME": assignment.crop_name,
                                        "CROP_PROVENANCE_JSON": json.dumps(
                                            assignment.to_dict()
                                        ),
                                        "TIMEZONE": timezone_label,
                                        "RANDOM_SEED": stable_seed(master_seed, "planting", year),
                                        "CREATE_REVIEW": False,
                                        "OUTPUT_DIR": str(temporary_path),
                                        **planting_processing_parameters(crop_planting_settings),
                                    },
                                )
                            )
                    if enabled["applications"]:
                        for operation in (
                            item for item in application_operations if item["year"] == year
                        ):
                            operation_id = operation["operation_id"]
                            tasks.append(
                                (
                                    f"applications_{year}_{operation_id}",
                                    "fake_farm_data_generator:create_fake_as_applied_data",
                                    {
                                        "INPUT": normalized_source,
                                        "UNIT_SYSTEM": unit_index,
                                        "TIMEZONE": timezone_label,
                                        **operation_to_processing_parameters(operation),
                                        "RANDOM_SEED": stable_seed(
                                            master_seed,
                                            "applications",
                                            year,
                                            operation_id,
                                        ),
                                        "CREATE_REVIEW": False,
                                        "OUTPUT_DIR": str(temporary_path),
                                    },
                                )
                            )
                    if enabled["yield"]:
                        for field_id, field_layer in field_layers.items():
                            assignment = crop_assignments[(field_id, year)]
                            assignment_index = CreateFakeYieldAlgorithm.CROP_OPTIONS.index(
                                assignment.crop_name
                            )
                            profile_min, profile_max, profile_moisture, _unit = (
                                CreateFakeYieldAlgorithm.CROP_PROFILES[assignment.crop_name]
                            )
                            if units.metric:
                                profile_min, profile_max, _unit = metric_yield_profile(
                                    assignment.crop_name,
                                    profile_min,
                                    profile_max,
                                    _unit,
                                )
                            profile_override = yield_settings.get(
                                "profile_overrides", {}
                            ).get(assignment.crop_name)
                            if profile_override:
                                profile_min = profile_override["min_yield"]
                                profile_max = profile_override["max_yield"]
                                profile_moisture = profile_override["standard_moisture"]
                                minimum_moisture = profile_override["min_moisture"]
                                maximum_moisture = profile_override["max_moisture"]
                            else:
                                minimum_moisture = max(0.0, profile_moisture - 3.0)
                                maximum_moisture = min(99.0, profile_moisture + 8.0)
                            tasks.append(
                                (
                                    f"yield_{field_id}_{year}",
                                    "fake_farm_data_generator:create_fake_yield_data",
                                    {
                                        "INPUT": field_layer,
                                        "UNIT_SYSTEM": unit_index,
                                        "CROP_YEAR": year,
                                        "CROP_PROFILE": assignment_index,
                                        "CROP_PROVENANCE_JSON": json.dumps(
                                            assignment.to_dict()
                                        ),
                                        "TIMEZONE": timezone_label,
                                        "MIN_DRY_YIELD": profile_min,
                                        "MAX_DRY_YIELD": profile_max,
                                        "STANDARD_MOISTURE": profile_moisture,
                                        "MIN_MOISTURE": minimum_moisture,
                                        "MAX_MOISTURE": maximum_moisture,
                                        "RANDOM_SEED": stable_seed(master_seed, "yield", year),
                                        "CREATE_REVIEW": False,
                                        "OUTPUT_DIR": str(temporary_path),
                                        **yield_processing_parameters(yield_settings),
                                    },
                                )
                            )
                import processing

                task_totals = {
                    "soil": estimates.get("soil_points", 0)
                    + estimates.get("soil_surface_cells", 0),
                    "planting": estimates.get("planter_center_points", 0)
                    + estimates.get("planting_row_unit_points", 0)
                    + estimates.get("planting_surface_cells", 0),
                    "applications": estimates.get("application_points", 0)
                    + estimates.get("application_surface_cells", 0),
                    "yield": estimates.get("yield_points", 0)
                    + estimates.get("yield_surface_cells", 0),
                }
                task_counts = {
                    key: sum(
                        1
                        for name, _algorithm, _parameters in tasks
                        if name == key or name.startswith(f"{key}_")
                    )
                    for key in task_totals
                }
                task_weights = []
                for component_name, _algorithm, _parameters in tasks:
                    kind = next(
                        (
                            key
                            for key in task_totals
                            if component_name == key
                            or component_name.startswith(f"{key}_")
                        ),
                        component_name,
                    )
                    task_weights.append(
                        max(
                            1.0,
                            float(task_totals.get(kind, 1))
                            / max(1, task_counts.get(kind, 1)),
                        )
                    )
                total_task_weight = max(1.0, sum(task_weights))
                completed_weight = 0.0
                feedback.setProgress(3)
                feedback.pushInfo(
                    "FFDG_OVERALL_PROGRESS|3|Prepared field boundaries and run metadata"
                )
                for index, (component_name, algorithm_id, child_parameters) in enumerate(tasks):
                    if feedback.isCanceled():
                        manifest["status"] = "incomplete"
                        break
                    start_percent = 3.0 + 85.0 * completed_weight / total_task_weight
                    end_percent = 3.0 + 85.0 * (
                        completed_weight + task_weights[index]
                    ) / total_task_weight
                    component_feedback = _ScaledComponentFeedback(
                        feedback, start_percent, end_percent, component_name
                    )
                    feedback.pushInfo(
                        f"Complete run component {index + 1}/{len(tasks)}: {component_name}"
                    )
                    result = processing.run(
                        algorithm_id,
                        child_parameters,
                        context=context,
                        feedback=component_feedback,
                        is_child_algorithm=True,
                    )
                    child_manifest, copied = self._copy_component(
                        result["OUTPUT_FOLDER"], run_folder, component_name, manifest["outputs"]
                    )
                    manifest["components"].append(
                        {
                            "name": component_name,
                            "algorithm": algorithm_id,
                            "status": child_manifest.get("status"),
                            "counts": child_manifest.get("counts", {}),
                            "outputs": copied,
                        }
                    )
                    for key, value in child_manifest.get("counts", {}).items():
                        manifest["counts"][key] = manifest["counts"].get(key, 0) + value
                    completed_weight += task_weights[index]
                    feedback.setProgress(end_percent)
                    feedback.pushInfo(
                        f"FFDG_OVERALL_PROGRESS|{int(end_percent)}|Completed {component_name} "
                        f"({index + 1}/{len(tasks)} components)"
                    )
            del normalized_source
            if manifest["status"] == "running":
                consolidation_feedback = _ScaledComponentFeedback(
                    feedback, 88, 93, "yearly GeoPackages"
                )
                consolidation_feedback.setProgress(0)
                yearly_geopackages = consolidate_complete_run_geopackages(
                    run_folder, manifest, years, consolidation_feedback
                )
                write_gpkg_run_metadata(yearly_geopackages, manifest)
                export_feedback = _ScaledComponentFeedback(
                    feedback, 93, 97, "selected output formats"
                )
                export_feedback.setProgress(0)
                export_vector_derivatives(
                    run_folder, manifest, output_formats, export_feedback
                )
                review_feedback = _ScaledComponentFeedback(
                    feedback, 97, 99, "portable HTML review"
                )
                review_feedback.setProgress(0)
                review_path, review_data_folder = build_portable_review(
                    run_folder, manifest, review_max_features, review_feedback
                )
                manifest["outputs"].extend(
                    [
                        str(review_path.relative_to(run_folder)),
                        str((review_data_folder / "layers.js").relative_to(run_folder)),
                    ]
                )
                manifest["status"] = "complete"
                feedback.setProgress(100)
                feedback.pushInfo(
                    "FFDG_OVERALL_PROGRESS|100|Finalized manifest and completed run"
                )
        except Exception as error:
            manifest["status"] = "incomplete"
            manifest["error"] = str(error)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            raise

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        feedback.pushInfo(FAKE_WARNING)
        return {
            self.OUTPUT_FOLDER: str(run_folder),
            self.MANIFEST: str(manifest_path),
            self.RECIPE: str(recipe_path),
        }
