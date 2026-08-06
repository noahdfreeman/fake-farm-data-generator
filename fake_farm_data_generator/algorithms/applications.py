# SPDX-License-Identifier: GPL-3.0-or-later
"""Create deterministic fake as-applied logs and polygon-grid surfaces."""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, time, timedelta
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorFileWriter,
    QgsWkbTypes,
)

from ..core.generation import (
    FAKE_WARNING,
    VARIABILITY_MULTIPLIERS,
    deterministic_operation_date,
    feature_field_id,
    feature_field_identity,
    normalize_timezone_label,
    stable_seed,
)
from ..core.units import UNIT_SYSTEM_OPTIONS, unit_system
from ..core.gpkg_metadata import write_gpkg_run_metadata
from ..core.progress import ProgressReporter
from ..exporters import OUTPUT_FORMAT_OPTIONS, export_vector_derivatives
from ..review.builder import build_portable_review
from ..core.review_settings import (
    DEFAULT_REVIEW_MAX_FEATURES,
    MAX_REVIEW_MAX_FEATURES,
    MIN_REVIEW_MAX_FEATURES,
    normalize_review_max_features,
)
from .planting import CreateFakePlantingAlgorithm


class CreateFakeApplicationsAlgorithm(QgsProcessingAlgorithm):
    """Generate one configured fake as-applied operation."""

    INPUT = "INPUT"
    UNIT_SYSTEM = "UNIT_SYSTEM"
    CROP_YEAR = "CROP_YEAR"
    OPERATION_ID = "OPERATION_ID"
    OPERATION_TYPE = "OPERATION_TYPE"
    PRODUCT_NAME = "PRODUCT_NAME"
    RATE_MODE = "RATE_MODE"
    TARGET_RATE = "TARGET_RATE"
    MIN_RATE = "MIN_RATE"
    MAX_RATE = "MAX_RATE"
    RATE_UNIT = "RATE_UNIT"
    EQUIPMENT_WIDTH = "EQUIPMENT_WIDTH"
    NOMINAL_SPEED = "NOMINAL_SPEED"
    LOGGING_INTERVAL = "LOGGING_INTERVAL"
    HEADLAND_PASSES = "HEADLAND_PASSES"
    DIRECTION_MODE = "DIRECTION_MODE"
    MANUAL_BEARING = "MANUAL_BEARING"
    APPLICATION_MONTH_DAY = "APPLICATION_MONTH_DAY"
    DATE_WINDOW = "DATE_WINDOW"
    TIMEZONE = "TIMEZONE"
    VARIABILITY_LEVEL = "VARIABILITY_LEVEL"
    CREATE_SURFACE = "CREATE_SURFACE"
    SURFACE_GRID_SIZE = "SURFACE_GRID_SIZE"
    RANDOM_SEED = "RANDOM_SEED"
    OUTPUT_FORMATS = "OUTPUT_FORMATS"
    CREATE_REVIEW = "CREATE_REVIEW"
    REVIEW_MAX_FEATURES = "REVIEW_MAX_FEATURES"
    OUTPUT_DIR = "OUTPUT_DIR"

    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    POINT_LAYER = "POINT_LAYER"
    SURFACE_LAYER = "SURFACE_LAYER"
    MANIFEST = "MANIFEST"

    OPERATION_OPTIONS = [
        "Dry Fertilizer",
        "Liquid Fertilizer",
        "Lime",
        "Chemical Spraying",
        "Manure",
        "Seeding or Broadcast Seeding",
    ]
    RATE_MODE_OPTIONS = ["Flat Rate", "Variable Rate"]
    DIRECTION_OPTIONS = ["Automatic", "Manual"]
    VARIABILITY_OPTIONS = ["Low", "Medium", "High"]

    def tr(self, text):
        return QCoreApplication.translate("FakeFarmDataGenerator", text)

    def createInstance(self):
        return CreateFakeApplicationsAlgorithm()

    def name(self):
        return "create_fake_as_applied_data"

    def displayName(self):
        return self.tr("Create Fake As-Applied Data")

    def group(self):
        return self.tr("Fake Farm Data Generator")

    def groupId(self):
        return "fake_farm_data_generator"

    def shortHelpString(self):
        return self.tr(
            "Creates clearly labeled fake as-applied center-log points and an optional "
            "polygon-grid surface. Flat settings retain small logged variation; variable "
            "settings add a larger smooth fake target-rate pattern. No prescription, soil, "
            "yield, DEM, or weather input is used. Outputs are not for agronomic decisions."
        )

    def initAlgorithm(self, config=None):
        current_year = datetime.now().year
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr("Field boundaries (selected features take precedence)"),
                [QgsProcessing.SourceType.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.UNIT_SYSTEM, self.tr("Unit system"), UNIT_SYSTEM_OPTIONS, False, 0
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.CROP_YEAR,
                self.tr("Operation year"),
                QgsProcessingParameterNumber.Type.Integer,
                current_year,
                False,
                1900,
                2100,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.OPERATION_ID, self.tr("Operation ID"), "APP_001"
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.OPERATION_TYPE,
                self.tr("Operation type"),
                self.OPERATION_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.PRODUCT_NAME, self.tr("Product name"), "Fake Product"
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.RATE_MODE,
                self.tr("Rate mode"),
                self.RATE_MODE_OPTIONS,
                False,
                0,
            )
        )
        for name, label, default in (
            (self.TARGET_RATE, "Target rate", 150.0),
            (self.MIN_RATE, "Minimum logged rate", 120.0),
            (self.MAX_RATE, "Maximum logged rate", 180.0),
        ):
            self.addParameter(
                QgsProcessingParameterNumber(
                    name,
                    self.tr(label),
                    QgsProcessingParameterNumber.Type.Double,
                    default,
                    False,
                    0.0,
                    1000000.0,
                )
            )
        self.addParameter(
            QgsProcessingParameterString(
                self.RATE_UNIT, self.tr("Rate unit"), "lb/acre"
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.EQUIPMENT_WIDTH,
                self.tr("Equipment width (ft Imperial; m Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                60.0,
                False,
                1.0,
                300.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.NOMINAL_SPEED,
                self.tr("Nominal speed (mph Imperial; km/h Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                10.0,
                False,
                0.1,
                60.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.LOGGING_INTERVAL,
                self.tr("Logging interval (seconds)"),
                QgsProcessingParameterNumber.Type.Double,
                1.0,
                False,
                0.1,
                60.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEADLAND_PASSES,
                self.tr("Headland passes"),
                QgsProcessingParameterNumber.Type.Integer,
                2,
                False,
                0.0,
                20.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.DIRECTION_MODE,
                self.tr("Travel direction"),
                self.DIRECTION_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MANUAL_BEARING,
                self.tr("Manual bearing (degrees clockwise from north)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                0.0,
                359.999,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.APPLICATION_MONTH_DAY,
                self.tr("Default application date (MM-DD)"),
                "04-15",
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.DATE_WINDOW,
                self.tr("Random date window (+/- days)"),
                QgsProcessingParameterNumber.Type.Integer,
                14,
                False,
                0,
                90,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TIMEZONE,
                self.tr("Timezone label for timestamps (optional; e.g. America/Indianapolis)"),
                "",
                False,
                True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.VARIABILITY_LEVEL,
                self.tr("Variability level"),
                self.VARIABILITY_OPTIONS,
                False,
                1,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CREATE_SURFACE,
                self.tr("Create as-applied polygon-grid surface"),
                True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SURFACE_GRID_SIZE,
                self.tr("Surface grid-cell size (ft Imperial; m Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                30.0,
                False,
                5.0,
                1000.0,
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
            QgsProcessingParameterBoolean(
                self.CREATE_REVIEW, self.tr("Create portable HTML review"), True
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
                self.OUTPUT_FORMATS, self.tr("Output formats"), OUTPUT_FORMAT_OPTIONS, True, [0]
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_DIR, self.tr("Parent output directory")
            )
        )
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_FOLDER, "Run folder"))
        self.addOutput(QgsProcessingOutputString(self.POINT_LAYER, "As-applied point layer"))
        self.addOutput(QgsProcessingOutputString(self.SURFACE_LAYER, "As-applied surface"))
        self.addOutput(QgsProcessingOutputString(self.MANIFEST, "Run manifest"))

    @staticmethod
    def _common_fields():
        fields = QgsFields()
        for name, variant in (
            ("fake_data", QVariant.Bool),
            ("fake_warning", QVariant.String),
            ("generator_name", QVariant.String),
            ("generator_version", QVariant.String),
            ("run_id", QVariant.String),
            ("created_at", QVariant.String),
            ("master_seed", QVariant.Int),
            ("child_seed", QVariant.Int),
            ("unit_system", QVariant.String),
            ("data_type", QVariant.String),
            ("field_id", QVariant.String),
            ("field_name", QVariant.String),
            ("farm_name", QVariant.String),
            ("grower_name", QVariant.String),
            ("crop_year", QVariant.Int),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @classmethod
    def _point_fields(cls):
        fields = cls._common_fields()
        for name, variant in (
            ("application_id", QVariant.String),
            ("operation_id", QVariant.String),
            ("operation_type", QVariant.String),
            ("product_name", QVariant.String),
            ("rate_mode", QVariant.String),
            ("target_rate", QVariant.Double),
            ("actual_rate", QVariant.Double),
            ("rate_unit", QVariant.String),
            ("pass_id", QVariant.String),
            ("timestamp", QVariant.String),
            ("timezone", QVariant.String),
            ("heading", QVariant.Double),
            ("speed", QVariant.Double),
            ("speed_unit", QVariant.String),
            ("equipment_width", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("section_on", QVariant.Bool),
            ("is_headland", QVariant.Bool),
            ("fake_terrain_effect", QVariant.Double),
            ("variability_level", QVariant.String),
            ("variability_multiplier", QVariant.Double),
            ("latitude", QVariant.Double),
            ("longitude", QVariant.Double),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @classmethod
    def _surface_fields(cls):
        fields = cls._common_fields()
        for name, variant in (
            ("cell_id", QVariant.String),
            ("operation_id", QVariant.String),
            ("operation_type", QVariant.String),
            ("product_name", QVariant.String),
            ("rate_mode", QVariant.String),
            ("target_rate", QVariant.Double),
            ("actual_rate", QVariant.Double),
            ("rate_unit", QVariant.String),
            ("speed", QVariant.Double),
            ("speed_unit", QVariant.String),
            ("fake_terrain_effect", QVariant.Double),
            ("grid_size", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("surface_method", QVariant.String),
            ("source_points", QVariant.Int),
            ("heading", QVariant.Double),
            ("is_headland", QVariant.Bool),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @staticmethod
    def _common_values(run, child_seed, data_type, field_id, year):
        identity = run["field_identities"].get(
            field_id,
            {"field_id": field_id, "field_name": field_id, "farm_name": "", "grower_name": ""},
        )
        return {
            "fake_data": True,
            "fake_warning": FAKE_WARNING,
            "generator_name": "Fake Farm Data Generator",
            "generator_version": "1.0.1",
            "run_id": run["run_id"],
            "created_at": run["created_at"],
            "master_seed": run["master_seed"],
            "child_seed": child_seed,
            "unit_system": run["unit_system"],
            "data_type": data_type,
            **identity,
            "crop_year": year,
        }

    @classmethod
    def _set_common(cls, feature, run, child_seed, data_type, field_id, year):
        for name, value in cls._common_values(
            run, child_seed, data_type, field_id, year
        ).items():
            feature.setAttribute(name, value)

    @staticmethod
    def _effects(point, bbox, seed, pass_number, rate_mode, target, minimum, maximum, nominal_speed, multiplier, headland):
        # This seeded generator is part of reproducible fake data, not cryptography.
        rng = random.Random(seed)  # nosec B311
        spatial = CreateFakePlantingAlgorithm._spatial_effect(point, bbox, seed)
        terrain = max(-1.0, min(1.0, 0.72 * spatial + 0.28 * math.sin(pass_number * 0.93)))
        pass_effect = math.sin(pass_number * 1.37 + (seed % 101) / 101.0)
        if rate_mode == "Variable Rate":
            desired = target + spatial * (maximum - minimum) * 0.42
            desired += pass_effect * (maximum - minimum) * 0.08
            noise_scale = max(0.001, target * 0.008 * multiplier)
        else:
            desired = target * (1.0 + spatial * 0.006 * multiplier + pass_effect * 0.003 * multiplier)
            noise_scale = max(0.001, target * 0.004 * multiplier)
        if headland:
            desired *= 0.985
        actual = max(minimum, min(maximum, desired + rng.gauss(0.0, noise_scale)))
        speed_factor = 1.0 - terrain * 0.025 * multiplier + rng.gauss(0.0, 0.006 * multiplier)
        if headland:
            speed_factor *= 0.82
        speed = max(nominal_speed * 0.35, min(nominal_speed * 1.35, nominal_speed * speed_factor))
        return {
            "target_rate": max(minimum, min(maximum, desired)),
            "actual_rate": actual,
            "speed": speed,
            "fake_terrain_effect": terrain,
        }

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException("Invalid field-boundary layer")
        features, used_selection = CreateFakePlantingAlgorithm._selected_or_all(source)
        if not features:
            raise QgsProcessingException("No field polygons were available to process")
        if len(features) > 20:
            raise QgsProcessingException("No more than 20 field polygons may be processed")
        units = unit_system(self.parameterAsEnum(parameters, self.UNIT_SYSTEM, context))
        year = self.parameterAsInt(parameters, self.CROP_YEAR, context)
        operation_id = self.parameterAsString(parameters, self.OPERATION_ID, context).strip()
        product_name = self.parameterAsString(parameters, self.PRODUCT_NAME, context).strip()
        rate_unit = self.parameterAsString(parameters, self.RATE_UNIT, context).strip()
        convert_default_rate = units.metric and rate_unit == "lb/acre"
        if convert_default_rate:
            rate_unit = "kg/ha"
        if not operation_id or not product_name or not rate_unit:
            raise QgsProcessingException("Operation ID, product name, and rate unit are required")
        operation_type = self.OPERATION_OPTIONS[
            self.parameterAsEnum(parameters, self.OPERATION_TYPE, context)
        ]
        rate_mode = self.RATE_MODE_OPTIONS[
            self.parameterAsEnum(parameters, self.RATE_MODE, context)
        ]
        target_rate = self.parameterAsDouble(parameters, self.TARGET_RATE, context)
        minimum_rate = self.parameterAsDouble(parameters, self.MIN_RATE, context)
        maximum_rate = self.parameterAsDouble(parameters, self.MAX_RATE, context)
        if convert_default_rate:
            target_rate *= 1.120851156
            minimum_rate *= 1.120851156
            maximum_rate *= 1.120851156
        if not minimum_rate <= target_rate <= maximum_rate:
            raise QgsProcessingException("Rate values must satisfy minimum <= target <= maximum")
        equipment_width_ft = self.parameterAsDouble(parameters, self.EQUIPMENT_WIDTH, context)
        nominal_speed = self.parameterAsDouble(parameters, self.NOMINAL_SPEED, context)
        logging_interval = self.parameterAsDouble(parameters, self.LOGGING_INTERVAL, context)
        headland_passes = self.parameterAsInt(parameters, self.HEADLAND_PASSES, context)
        direction_mode = self.DIRECTION_OPTIONS[
            self.parameterAsEnum(parameters, self.DIRECTION_MODE, context)
        ]
        manual_bearing = self.parameterAsDouble(parameters, self.MANUAL_BEARING, context)
        month, day = CreateFakePlantingAlgorithm._month_day(
            self.parameterAsString(parameters, self.APPLICATION_MONTH_DAY, context)
        )
        date_window = self.parameterAsInt(parameters, self.DATE_WINDOW, context)
        try:
            timezone_label = normalize_timezone_label(
                self.parameterAsString(parameters, self.TIMEZONE, context)
            )
        except ValueError as error:
            raise QgsProcessingException(str(error)) from error
        variability = self.VARIABILITY_OPTIONS[
            self.parameterAsEnum(parameters, self.VARIABILITY_LEVEL, context)
        ]
        multiplier = VARIABILITY_MULTIPLIERS[variability]
        create_surface = self.parameterAsBool(parameters, self.CREATE_SURFACE, context)
        surface_grid_size_ft = self.parameterAsDouble(parameters, self.SURFACE_GRID_SIZE, context)
        requested_seed = self.parameterAsInt(parameters, self.RANDOM_SEED, context)
        create_review = self.parameterAsBool(parameters, self.CREATE_REVIEW, context)
        review_max_features = normalize_review_max_features(
            self.parameterAsInt(parameters, self.REVIEW_MAX_FEATURES, context)
        )
        output_formats = [
            OUTPUT_FORMAT_OPTIONS[index]
            for index in self.parameterAsEnums(parameters, self.OUTPUT_FORMATS, context)
        ] or ["GeoPackage"]
        master_seed = requested_seed or random.SystemRandom().randint(1, 2_147_483_647)
        parent_output = Path(self.parameterAsString(parameters, self.OUTPUT_DIR, context))
        if not parent_output.is_dir():
            raise QgsProcessingException(f"Output directory does not exist: {parent_output}")

        source_crs = source.crs()
        transform_context = context.transformContext()
        working_crs = CreateFakePlantingAlgorithm._working_crs(
            source_crs, features, transform_context
        )
        to_working = QgsCoordinateTransform(source_crs, working_crs, transform_context)
        to_source = QgsCoordinateTransform(working_crs, source_crs, transform_context)
        to_wgs84 = QgsCoordinateTransform(
            working_crs, QgsCoordinateReferenceSystem("EPSG:4326"), transform_context
        )
        equipment_width_m = units.distance_to_meters(equipment_width_ft)
        headland_width_m = headland_passes * equipment_width_m
        surface_grid_size_m = units.distance_to_meters(surface_grid_size_ft)
        nominal_speed_mps = units.speed_to_meters_per_second(nominal_speed)
        point_spacing_m = nominal_speed_mps * logging_interval
        projected_fields = []
        total_area_m2 = 0.0
        for source_feature in features:
            geometry = QgsGeometry(source_feature.geometry())
            if geometry.isEmpty():
                projected_fields.append(None)
                continue
            geometry.transform(to_working)
            projected_fields.append(geometry)
            total_area_m2 += max(0.0, geometry.area())
        total_area_acres = total_area_m2 / 4046.8564224
        if total_area_acres > 5000.01:
            raise QgsProcessingException(
                f"Selected fields total {total_area_acres:,.1f} acres; the v1 limit is 5,000 acres"
            )
        estimated_points = max(
            1, int(math.ceil(total_area_m2 / max(0.01, equipment_width_m * point_spacing_m)))
        )
        estimated_cells = (
            int(math.ceil(total_area_m2 / max(0.01, surface_grid_size_m**2)))
            if create_surface
            else 0
        )
        feedback.pushInfo(
            f"Preflight estimate: {estimated_points:,} application points and "
            f"approximately {estimated_cells:,} surface cells"
        )
        if estimated_points + estimated_cells >= 100_000:
            feedback.pushWarning(
                "This run may take a while. QGIS must remain open until processing finishes."
            )

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_folder = parent_output / f"Fake_Farm_Data_{run_id}"
        run_folder.mkdir()
        year_folder = run_folder / str(year)
        year_folder.mkdir()
        run = {
            "run_id": run_id,
            "created_at": created_at,
            "master_seed": master_seed,
            "unit_system": units.name,
            "review_max_features": review_max_features,
            "timezone": timezone_label,
            "output_formats": output_formats,
            "field_identities": {
                feature_field_id(feature, index): feature_field_identity(feature, index)
                for index, feature in enumerate(features, start=1)
            },
        }
        point_fields = self._point_fields()
        point_field_names = point_fields.names()
        surface_fields = self._surface_fields() if create_surface else None
        point_path = year_folder / f"fake_applications_{year}.gpkg"
        surface_path = year_folder / f"fake_application_surface_{year}.gpkg"
        point_writer = CreateFakePlantingAlgorithm._writer(
            point_path, point_fields, source_crs, QgsWkbTypes.Type.Point, f"fake_applications_{year}"
        )
        surface_writer = (
            CreateFakePlantingAlgorithm._writer(
                surface_path,
                surface_fields,
                source_crs,
                QgsWkbTypes.Type.MultiPolygon,
                f"fake_application_surface_{year}",
            )
            if create_surface
            else None
        )
        manifest = {
            "schema_version": 1,
            "status": "running",
            "fake_data": True,
            "fake_warning": FAKE_WARNING,
            "generator": "Fake Farm Data Generator 1.0.1",
            "run_id": run_id,
            "created_at": created_at,
            "master_seed": master_seed,
            "used_selected_features": used_selection,
            "field_count": len(features),
            "total_area_acres": round(total_area_acres, 4),
            "total_area_hectares": round(total_area_m2 / 10000.0, 4),
            "unit_system": units.name,
            "review_max_features": review_max_features,
            "timezone": timezone_label,
            "years": [year],
            "application": {
                "operation_id": operation_id,
                "operation_type": operation_type,
                "product_name": product_name,
                "rate_mode": rate_mode,
                "target_rate": target_rate,
                "minimum_rate": minimum_rate,
                "maximum_rate": maximum_rate,
                "rate_unit": rate_unit,
                "equipment_width_feet": equipment_width_ft,
                "nominal_speed_mph": nominal_speed,
                "logging_interval_seconds": logging_interval,
                "headland_passes": headland_passes,
                "headland_width": round(
                    headland_width_m / units.distance_to_meters(1.0), 3
                ),
                "direction_mode": direction_mode,
                "variability_level": variability,
                "variability_multiplier": multiplier,
                "surface_created": create_surface,
                "surface_grid_size_feet": surface_grid_size_ft,
                "distance_unit": units.distance_unit,
                "speed_unit": units.speed_unit,
            },
            "field_bearings": {},
            "outputs": [],
            "estimates": {"application_points": estimated_points, "surface_cells": estimated_cells},
            "counts": {"application_points": 0, "surface_cells": 0},
        }
        manifest_path = run_folder / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        try:
            progress = ProgressReporter(feedback, len(features), "As-applied")
            operation_date = deterministic_operation_date(
                year,
                month,
                day,
                date_window,
                stable_seed(master_seed, operation_id, year, "date"),
            )
            operation_start = datetime.combine(operation_date, time(8, 0))
            point_counter = 1
            cell_counter = 1
            for field_index, (source_feature, geometry) in enumerate(
                zip(features, projected_fields), start=1
            ):
                if feedback.isCanceled():
                    manifest["status"] = "incomplete"
                    break
                field_id = feature_field_id(source_feature, field_index)
                if geometry is None or geometry.isEmpty() or geometry.area() <= 0:
                    feedback.pushWarning(f"Skipping empty or invalid geometry for {field_id}")
                    continue
                child_seed = stable_seed(master_seed, field_id, year, "application", operation_id)
                bearing = (
                    CreateFakePlantingAlgorithm._automatic_bearing(geometry)
                    if direction_mode == "Automatic"
                    else manual_bearing
                )
                manifest["field_bearings"][field_id] = round(bearing, 3)
                pass_specs, headland_interior = CreateFakePlantingAlgorithm._operation_passes(
                    geometry, bearing, equipment_width_m, headland_passes
                )
                bbox = geometry.boundingBox()
                samples = []
                elapsed_seconds = 0.0
                for pass_index, (original_line, pass_bearing, is_headland_pass) in enumerate(
                    pass_specs, start=1
                ):
                    if feedback.isCanceled():
                        manifest["status"] = "incomplete"
                        break
                    reverse = pass_index % 2 == 0
                    if reverse:
                        line = QgsGeometry.fromPolylineXY(list(reversed(original_line.asPolyline())))
                        pass_heading = (
                            (pass_bearing + 180.0) % 360.0
                            if pass_bearing is not None
                            else None
                        )
                    else:
                        line = original_line
                        pass_heading = (
                            pass_bearing % 360.0 if pass_bearing is not None else None
                        )
                    pass_id = f"A{field_index:03d}_{pass_index:04d}"
                    for position_index, (distance_along, point) in enumerate(
                        CreateFakePlantingAlgorithm._line_points(line, point_spacing_m), start=1
                    ):
                        heading = (
                            pass_heading
                            if pass_heading is not None
                            else CreateFakePlantingAlgorithm._line_heading(
                                line, distance_along
                            )
                        )
                        headland = is_headland_pass
                        values = self._effects(
                            point,
                            bbox,
                            stable_seed(child_seed, pass_index, position_index),
                            pass_index,
                            rate_mode,
                            target_rate,
                            minimum_rate,
                            maximum_rate,
                            nominal_speed,
                            multiplier,
                            headland,
                        )
                        timestamp = (
                            operation_start
                            + timedelta(
                                seconds=elapsed_seconds
                                + distance_along / max(0.01, nominal_speed_mps)
                            )
                        ).isoformat(timespec="seconds")
                        point_source = to_source.transform(QgsPointXY(point))
                        point_wgs84 = to_wgs84.transform(QgsPointXY(point))
                        feature = QgsFeature(point_fields)
                        feature.setGeometry(QgsGeometry.fromPointXY(point_source))
                        attributes = self._common_values(
                            run, child_seed, "as_applied_point", field_id, year
                        )
                        attributes.update({
                            "application_id": f"AP{year}_{field_index:03d}_{point_counter:08d}",
                            "operation_id": operation_id,
                            "operation_type": operation_type,
                            "product_name": product_name,
                            "rate_mode": rate_mode,
                            "target_rate": round(values["target_rate"], 4),
                            "actual_rate": round(values["actual_rate"], 4),
                            "rate_unit": rate_unit,
                            "pass_id": pass_id,
                            "timestamp": timestamp,
                            "timezone": timezone_label,
                            "heading": round(heading, 3),
                            "speed": round(values["speed"], 3),
                            "speed_unit": units.speed_unit,
                            "equipment_width": equipment_width_ft,
                            "distance_unit": units.distance_unit,
                            "section_on": True,
                            "is_headland": headland,
                            "fake_terrain_effect": round(values["fake_terrain_effect"], 5),
                            "variability_level": variability,
                            "variability_multiplier": multiplier,
                            "latitude": round(point_wgs84.y(), 7),
                            "longitude": round(point_wgs84.x(), 7),
                        })
                        feature.setAttributes(
                            [attributes.get(name) for name in point_field_names]
                        )
                        if not point_writer.addFeature(feature):
                            raise QgsProcessingException(
                                f"Could not write as-applied point for {field_id}"
                            )
                        samples.append((QgsPointXY(point), values))
                        point_counter += 1
                        manifest["counts"]["application_points"] += 1
                    elapsed_seconds += line.length() / max(0.01, nominal_speed_mps) + 30.0

                if feedback.isCanceled():
                    break
                if surface_writer is not None and samples:
                    buckets = {}
                    for sample_point, values in samples:
                        column = int((sample_point.x() - bbox.xMinimum()) // surface_grid_size_m)
                        row = int((sample_point.y() - bbox.yMinimum()) // surface_grid_size_m)
                        buckets.setdefault((column, row), []).append((sample_point, values))
                    row_index = 0
                    y = bbox.yMinimum()
                    while y < bbox.yMaximum():
                        column_index = 0
                        x = bbox.xMinimum()
                        while x < bbox.xMaximum():
                            cell = CreateFakePlantingAlgorithm._rectangle(
                                x,
                                y,
                                min(x + surface_grid_size_m, bbox.xMaximum()),
                                min(y + surface_grid_size_m, bbox.yMaximum()),
                            )
                            clipped = cell.intersection(geometry)
                            if not clipped.isEmpty() and clipped.area() > 0.001:
                                candidates = buckets.get((column_index, row_index), [])
                                local = [
                                    item
                                    for item in candidates
                                    if clipped.intersects(QgsGeometry.fromPointXY(item[0]))
                                ]
                                centroid = clipped.centroid().asPoint()
                                headland = headland_width_m > 0 and (
                                    headland_interior.isEmpty()
                                    or not headland_interior.intersects(
                                        QgsGeometry.fromPointXY(QgsPointXY(centroid))
                                    )
                                )
                                if local:
                                    values = {
                                        key: sum(item[1][key] for item in local) / len(local)
                                        for key in (
                                            "target_rate",
                                            "actual_rate",
                                            "speed",
                                            "fake_terrain_effect",
                                        )
                                    }
                                    method = "point_mean"
                                else:
                                    values = self._effects(
                                        centroid,
                                        bbox,
                                        stable_seed(child_seed, "surface", row_index, column_index),
                                        0,
                                        rate_mode,
                                        target_rate,
                                        minimum_rate,
                                        maximum_rate,
                                        nominal_speed,
                                        multiplier,
                                        headland,
                                    )
                                    method = "generated_centroid"
                                clipped.transform(to_source)
                                if not clipped.isMultipart():
                                    clipped.convertToMultiType()
                                feature = QgsFeature(surface_fields)
                                feature.setGeometry(clipped)
                                self._set_common(
                                    feature,
                                    run,
                                    child_seed,
                                    "as_applied_surface",
                                    field_id,
                                    year,
                                )
                                for name, value in {
                                    "cell_id": f"ASC{year}_{field_index:03d}_{cell_counter:07d}",
                                    "operation_id": operation_id,
                                    "operation_type": operation_type,
                                    "product_name": product_name,
                                    "rate_mode": rate_mode,
                                    "target_rate": round(values["target_rate"], 4),
                                    "actual_rate": round(values["actual_rate"], 4),
                                    "rate_unit": rate_unit,
                                    "speed": round(values["speed"], 3),
                                    "speed_unit": units.speed_unit,
                                    "fake_terrain_effect": round(values["fake_terrain_effect"], 5),
                                    "grid_size": surface_grid_size_ft,
                                    "distance_unit": units.distance_unit,
                                    "surface_method": method,
                                    "source_points": len(local),
                                    "heading": round(bearing, 3),
                                    "is_headland": headland,
                                }.items():
                                    feature.setAttribute(name, value)
                                if not surface_writer.addFeature(feature):
                                    raise QgsProcessingException(
                                        f"Could not write as-applied surface cell for {field_id}"
                                    )
                                cell_counter += 1
                                manifest["counts"]["surface_cells"] += 1
                            x += surface_grid_size_m
                            column_index += 1
                        y += surface_grid_size_m
                        row_index += 1
                progress.update(
                    field_index,
                    f"{operation_id} {field_id} {year}",
                    manifest["counts"]["application_points"]
                    + manifest["counts"]["surface_cells"],
                    force=True,
                )

            del point_writer
            del surface_writer
            manifest["outputs"].append(str(point_path.relative_to(run_folder)))
            if create_surface:
                manifest["outputs"].append(str(surface_path.relative_to(run_folder)))
            if manifest["status"] == "running":
                write_gpkg_run_metadata(
                    [point_path] + ([surface_path] if create_surface else []), manifest
                )
                export_vector_derivatives(run_folder, manifest, output_formats, feedback)
                if create_review:
                    review_path, review_data = build_portable_review(
                        run_folder, manifest, review_max_features, feedback
                    )
                    manifest["outputs"].extend(
                        [
                            str(review_path.relative_to(run_folder)),
                            str((review_data / "layers.js").relative_to(run_folder)),
                        ]
                    )
                manifest["status"] = "complete"
        except Exception as error:
            manifest["status"] = "incomplete"
            manifest["error"] = str(error)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            raise

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        feedback.pushInfo(FAKE_WARNING)
        feedback.pushInfo(
            f"Created {manifest['counts']['application_points']:,} as-applied points and "
            f"{manifest['counts']['surface_cells']:,} surface cells"
        )
        return {
            self.OUTPUT_FOLDER: str(run_folder),
            self.POINT_LAYER: str(point_path),
            self.SURFACE_LAYER: str(surface_path) if create_surface else "",
            self.MANIFEST: str(manifest_path),
        }
