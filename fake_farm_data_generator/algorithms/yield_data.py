# SPDX-License-Identifier: GPL-3.0-or-later
"""Create deterministic fake yield-monitor logs and polygon-grid surfaces."""

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
    QgsWkbTypes,
)

from ..core.generation import (
    FAKE_WARNING,
    VARIABILITY_MULTIPLIERS,
    crop_provenance_from_json,
    deterministic_operation_date,
    feature_field_id,
    feature_field_identity,
    normalize_timezone_label,
    stable_seed,
)
from ..core.units import METRIC_YIELD, UNIT_SYSTEM_OPTIONS, unit_system
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


class CreateFakeYieldAlgorithm(QgsProcessingAlgorithm):
    """Generate fake combine-style points and a clipped yield grid."""

    INPUT = "INPUT"
    UNIT_SYSTEM = "UNIT_SYSTEM"
    CROP_YEAR = "CROP_YEAR"
    CROP_PROFILE = "CROP_PROFILE"
    CROP_PROVENANCE_JSON = "CROP_PROVENANCE_JSON"
    MIN_DRY_YIELD = "MIN_DRY_YIELD"
    MAX_DRY_YIELD = "MAX_DRY_YIELD"
    MIN_MOISTURE = "MIN_MOISTURE"
    MAX_MOISTURE = "MAX_MOISTURE"
    STANDARD_MOISTURE = "STANDARD_MOISTURE"
    SWATH_WIDTH = "SWATH_WIDTH"
    NOMINAL_SPEED = "NOMINAL_SPEED"
    LOGGING_INTERVAL = "LOGGING_INTERVAL"
    HEADLAND_PASSES = "HEADLAND_PASSES"
    HEADLAND_PENALTY = "HEADLAND_PENALTY"
    DIRECTION_MODE = "DIRECTION_MODE"
    MANUAL_BEARING = "MANUAL_BEARING"
    HARVEST_MONTH_DAY = "HARVEST_MONTH_DAY"
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

    CROP_PROFILES = {
        "Corn": (120.0, 240.0, 15.5, "bu/acre"),
        "Soybeans": (35.0, 80.0, 13.0, "bu/acre"),
        "Wheat": (40.0, 100.0, 13.5, "bu/acre"),
        "Cotton": (0.6, 1.8, 8.0, "bales/acre"),
        "Grain Sorghum": (50.0, 140.0, 14.0, "bu/acre"),
        "Barley": (50.0, 120.0, 14.5, "bu/acre"),
        "Oats": (50.0, 140.0, 14.0, "bu/acre"),
        "Canola": (25.0, 70.0, 10.0, "bu/acre"),
        "Dry Beans": (12.0, 35.0, 18.0, "cwt/acre"),
        "Sunflowers": (900.0, 2600.0, 10.0, "lb/acre"),
        "Alfalfa": (2.0, 8.0, 15.0, "tons/acre"),
        "Other Crop": (1.0, 100.0, 15.0, "units/acre"),
    }
    CROP_OPTIONS = list(CROP_PROFILES)
    DIRECTION_OPTIONS = ["Automatic", "Manual"]
    VARIABILITY_OPTIONS = ["Low", "Medium", "High"]
    NATURAL_VARIABILITY = {
        "Low": {"noise_fraction": 0.04, "spatial_fraction": 0.08, "moisture_noise": 0.5},
        "Medium": {"noise_fraction": 0.08, "spatial_fraction": 0.15, "moisture_noise": 1.0},
        "High": {"noise_fraction": 0.14, "spatial_fraction": 0.25, "moisture_noise": 1.8},
    }

    def tr(self, text):
        return QCoreApplication.translate("FakeFarmDataGenerator", text)

    def createInstance(self):
        return CreateFakeYieldAlgorithm()

    def name(self):
        return "create_fake_yield_data"

    def displayName(self):
        return self.tr("Create Fake Yield Data")

    def group(self):
        return self.tr("Fake Farm Data Generator")

    def groupId(self):
        return "fake_farm_data_generator"

    def shortHelpString(self):
        return self.tr(
            "Creates clearly labeled fake combine-style yield points and an optional "
            "polygon-grid surface with dry yield, wet yield, moisture, speed, and "
            "headland effects. No soil, weather, terrain, or observed yield data is used."
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
                self.tr("Crop year"),
                QgsProcessingParameterNumber.Type.Integer,
                current_year,
                False,
                1900,
                2100,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CROP_PROFILE,
                self.tr("Crop profile"),
                self.CROP_OPTIONS,
                False,
                0,
            )
        )
        provenance_parameter = QgsProcessingParameterString(
            self.CROP_PROVENANCE_JSON,
            self.tr("Crop provenance JSON (advanced)"),
            "",
            False,
            True,
        )
        self.addParameter(provenance_parameter)
        for name, label, default, maximum in (
            (self.MIN_DRY_YIELD, "Minimum dry yield", 120.0, 100000.0),
            (self.MAX_DRY_YIELD, "Maximum dry yield", 240.0, 100000.0),
            (self.MIN_MOISTURE, "Minimum moisture (%)", 12.0, 99.0),
            (self.MAX_MOISTURE, "Maximum moisture (%)", 25.0, 99.0),
            (self.STANDARD_MOISTURE, "Standard moisture (%)", 15.5, 99.0),
        ):
            self.addParameter(
                QgsProcessingParameterNumber(
                    name,
                    self.tr(label),
                    QgsProcessingParameterNumber.Type.Double,
                    default,
                    False,
                    0.0,
                    maximum,
                )
            )
        for name, label, default, minimum, maximum in (
            (self.SWATH_WIDTH, "Header width (ft Imperial; m Metric)", 30.0, 1.0, 100.0),
            (self.NOMINAL_SPEED, "Harvest speed (mph Imperial; km/h Metric)", 4.0, 0.1, 60.0),
            (self.LOGGING_INTERVAL, "Logging interval (seconds)", 1.0, 0.1, 60.0),
            (self.HEADLAND_PENALTY, "Headland yield penalty (%)", 10.0, 0.0, 75.0),
        ):
            self.addParameter(
                QgsProcessingParameterNumber(
                    name,
                    self.tr(label),
                    QgsProcessingParameterNumber.Type.Double,
                    default,
                    False,
                    minimum,
                    maximum,
                )
            )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HEADLAND_PASSES,
                self.tr("Headland passes"),
                QgsProcessingParameterNumber.Type.Integer,
                3,
                False,
                0,
                20,
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
                self.HARVEST_MONTH_DAY,
                self.tr("Default harvest date (MM-DD)"),
                "10-15",
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
                self.CREATE_SURFACE, self.tr("Create yield polygon-grid surface"), True
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
        self.addOutput(QgsProcessingOutputString(self.POINT_LAYER, "Yield point layer"))
        self.addOutput(QgsProcessingOutputString(self.SURFACE_LAYER, "Yield surface"))
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
            ("crop_name", QVariant.String),
            ("crop_code", QVariant.String),
            ("crop_pct", QVariant.Double),
            ("crop_source", QVariant.String),
            ("crop_source_year", QVariant.Int),
            ("crop_resolution", QVariant.Double),
            ("crop_lookup_at", QVariant.String),
            ("crop_overridden", QVariant.Bool),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @classmethod
    def _point_fields(cls):
        fields = cls._common_fields()
        for name, variant in (
            ("yield_id", QVariant.String),
            ("pass_id", QVariant.String),
            ("timestamp", QVariant.String),
            ("timezone", QVariant.String),
            ("heading", QVariant.Double),
            ("dry_yield", QVariant.Double),
            ("wet_yield", QVariant.Double),
            ("yield_unit", QVariant.String),
            ("moisture_pct", QVariant.Double),
            ("standard_moisture", QVariant.Double),
            ("speed", QVariant.Double),
            ("speed_unit", QVariant.String),
            ("swath_width", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("logging_interval_sec", QVariant.Double),
            ("is_headland", QVariant.Bool),
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
            ("dry_yield", QVariant.Double),
            ("wet_yield", QVariant.Double),
            ("yield_unit", QVariant.String),
            ("moisture_pct", QVariant.Double),
            ("standard_moisture", QVariant.Double),
            ("speed", QVariant.Double),
            ("speed_unit", QVariant.String),
            ("is_headland", QVariant.Bool),
            ("grid_size", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("surface_method", QVariant.String),
            ("source_points", QVariant.Int),
            ("heading", QVariant.Double),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @staticmethod
    def _common_values(run, child_seed, data_type, field_id, year, crop_name):
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
            **run["crop_provenance"],
        }

    @classmethod
    def _set_common(cls, feature, run, child_seed, data_type, field_id, year, crop_name):
        for name, value in cls._common_values(
            run, child_seed, data_type, field_id, year, crop_name
        ).items():
            feature.setAttribute(name, value)

    @staticmethod
    def _field_pattern(field_seed, minimum_yield, maximum_yield):
        # This seeded generator is part of reproducible fake data, not cryptography.
        field_rng = random.Random(  # nosec B311
            stable_seed(field_seed, "natural_yield_pattern")
        )
        range_width = maximum_yield - minimum_yield
        return (
            field_rng.uniform(
                minimum_yield + range_width * 0.25,
                maximum_yield - range_width * 0.25,
            ),
            field_rng.uniform(0.0, 2.0 * math.pi),
            field_rng.uniform(0.0, 2.0 * math.pi),
        )

    @staticmethod
    def _values(point, bbox, sample_seed, field_pattern, minimum_yield, maximum_yield, minimum_moisture, maximum_moisture, standard_moisture, nominal_speed, variability_level, headland, headland_penalty, noise_scale=1.0):
        """Replicate the original smooth field pattern with deterministic noise."""

        # This seeded generator is part of reproducible fake data, not cryptography.
        rng = random.Random(sample_seed)  # nosec B311
        range_width = maximum_yield - minimum_yield
        field_base_yield, phase_x, phase_y = field_pattern
        width = max(0.001, bbox.width())
        height = max(0.001, bbox.height())
        x_norm = (point.x() - bbox.xMinimum()) / width
        y_norm = (point.y() - bbox.yMinimum()) / height
        gradient = (x_norm - 0.5) * 0.55 + (y_norm - 0.5) * 0.35
        wave_1 = math.sin(x_norm * 2.0 * math.pi + phase_x) * 0.45
        wave_2 = math.cos(y_norm * 2.0 * math.pi + phase_y) * 0.35
        wave_3 = math.sin(
            (x_norm + y_norm) * 2.0 * math.pi + phase_x + phase_y
        ) * 0.20
        settings = CreateFakeYieldAlgorithm.NATURAL_VARIABILITY[variability_level]
        spatial_pattern = gradient + wave_1 + wave_2 + wave_3
        spatial_multiplier = 1.0 + settings["spatial_fraction"] * spatial_pattern
        dry_yield = field_base_yield * spatial_multiplier
        dry_yield += rng.gauss(
            0.0,
            max(0.001, range_width * settings["noise_fraction"] * noise_scale),
        )
        if headland:
            dry_yield *= 1.0 - headland_penalty / 100.0
        dry_yield = max(minimum_yield, min(maximum_yield, dry_yield))
        moisture_midpoint = (minimum_moisture + maximum_moisture) / 2.0
        moisture = moisture_midpoint + (y_norm - 0.5)
        moisture += rng.gauss(
            0.0, max(0.01, settings["moisture_noise"] * noise_scale)
        )
        moisture = max(minimum_moisture, min(maximum_moisture, moisture))
        wet_yield = dry_yield * (100.0 - standard_moisture) / max(0.01, 100.0 - moisture)
        speed_factor = 1.0 + spatial_pattern * 0.018 + rng.gauss(0.0, 0.006)
        if headland:
            speed_factor *= 0.82
        speed = max(nominal_speed * 0.35, min(nominal_speed * 1.35, nominal_speed * speed_factor))
        return {
            "dry_yield": dry_yield,
            "wet_yield": wet_yield,
            "moisture_pct": moisture,
            "speed": speed,
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
        crop_name = self.CROP_OPTIONS[
            self.parameterAsEnum(parameters, self.CROP_PROFILE, context)
        ]
        try:
            crop_provenance = crop_provenance_from_json(
                self.parameterAsString(parameters, self.CROP_PROVENANCE_JSON, context),
                crop_name,
                year,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise QgsProcessingException(str(error)) from error
        yield_unit = (
            METRIC_YIELD[crop_name][1]
            if units.metric
            else self.CROP_PROFILES[crop_name][3]
        )
        minimum_yield = self.parameterAsDouble(parameters, self.MIN_DRY_YIELD, context)
        maximum_yield = self.parameterAsDouble(parameters, self.MAX_DRY_YIELD, context)
        minimum_moisture = self.parameterAsDouble(parameters, self.MIN_MOISTURE, context)
        maximum_moisture = self.parameterAsDouble(parameters, self.MAX_MOISTURE, context)
        standard_moisture = self.parameterAsDouble(parameters, self.STANDARD_MOISTURE, context)
        if minimum_yield >= maximum_yield:
            raise QgsProcessingException("Minimum dry yield must be less than maximum dry yield")
        if not minimum_moisture <= standard_moisture <= maximum_moisture:
            raise QgsProcessingException(
                "Moisture values must satisfy minimum <= standard <= maximum"
            )
        swath_width_ft = self.parameterAsDouble(parameters, self.SWATH_WIDTH, context)
        nominal_speed = self.parameterAsDouble(parameters, self.NOMINAL_SPEED, context)
        logging_interval = self.parameterAsDouble(parameters, self.LOGGING_INTERVAL, context)
        headland_passes = self.parameterAsInt(parameters, self.HEADLAND_PASSES, context)
        headland_penalty = self.parameterAsDouble(parameters, self.HEADLAND_PENALTY, context)
        direction_mode = self.DIRECTION_OPTIONS[
            self.parameterAsEnum(parameters, self.DIRECTION_MODE, context)
        ]
        manual_bearing = self.parameterAsDouble(parameters, self.MANUAL_BEARING, context)
        month, day = CreateFakePlantingAlgorithm._month_day(
            self.parameterAsString(parameters, self.HARVEST_MONTH_DAY, context)
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
        swath_width_m = units.distance_to_meters(swath_width_ft)
        headland_width_m = headland_passes * swath_width_m
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
            1, int(math.ceil(total_area_m2 / max(0.01, swath_width_m * point_spacing_m)))
        )
        estimated_cells = (
            int(math.ceil(total_area_m2 / max(0.01, surface_grid_size_m**2)))
            if create_surface
            else 0
        )
        feedback.pushInfo(
            f"Preflight estimate: {estimated_points:,} yield points and approximately "
            f"{estimated_cells:,} surface cells"
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
            "crop_provenance": crop_provenance,
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
        point_path = year_folder / f"fake_yield_points_{year}.gpkg"
        surface_path = year_folder / f"fake_yield_surface_{year}.gpkg"
        point_writer = CreateFakePlantingAlgorithm._writer(
            point_path, point_fields, source_crs, QgsWkbTypes.Type.Point, f"fake_yield_points_{year}"
        )
        surface_writer = (
            CreateFakePlantingAlgorithm._writer(
                surface_path,
                surface_fields,
                source_crs,
                QgsWkbTypes.Type.MultiPolygon,
                f"fake_yield_surface_{year}",
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
            "yield": {
                "crop_name": crop_name,
                "crop_provenance": crop_provenance,
                "yield_unit": yield_unit,
                "minimum_dry_yield": minimum_yield,
                "maximum_dry_yield": maximum_yield,
                "minimum_moisture": minimum_moisture,
                "maximum_moisture": maximum_moisture,
                "standard_moisture": standard_moisture,
                "swath_width_feet": swath_width_ft,
                "nominal_speed_mph": nominal_speed,
                "logging_interval_seconds": logging_interval,
                "headland_passes": headland_passes,
                "headland_width": round(
                    headland_width_m / units.distance_to_meters(1.0), 3
                ),
                "headland_penalty_percent": headland_penalty,
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
            "estimates": {"yield_points": estimated_points, "surface_cells": estimated_cells},
            "counts": {"yield_points": 0, "surface_cells": 0},
        }
        manifest_path = run_folder / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        try:
            estimated_work = max(1, estimated_points + estimated_cells)
            progress = ProgressReporter(
                feedback,
                estimated_work,
                "Yield",
                minimum_message_interval=1.0,
            )
            harvest_date = deterministic_operation_date(
                year,
                month,
                day,
                date_window,
                stable_seed(master_seed, crop_name, year, "harvest_date"),
            )
            operation_start = datetime.combine(harvest_date, time(9, 0))
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
                child_seed = stable_seed(master_seed, field_id, year, "yield")
                field_pattern = self._field_pattern(
                    child_seed, minimum_yield, maximum_yield
                )
                bearing = (
                    CreateFakePlantingAlgorithm._automatic_bearing(geometry)
                    if direction_mode == "Automatic"
                    else manual_bearing
                )
                manifest["field_bearings"][field_id] = round(bearing, 3)
                pass_specs, headland_interior = CreateFakePlantingAlgorithm._operation_passes(
                    geometry, bearing, swath_width_m, headland_passes
                )
                bbox = geometry.boundingBox()
                samples = []
                elapsed_seconds = 0.0
                for pass_index, (original_line, pass_bearing, is_end_row) in enumerate(
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
                    pass_id = f"Y{field_index:03d}_{pass_index:04d}"
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
                        headland = is_end_row
                        values = self._values(
                            point,
                            bbox,
                            stable_seed(child_seed, pass_index, position_index),
                            field_pattern,
                            minimum_yield,
                            maximum_yield,
                            minimum_moisture,
                            maximum_moisture,
                            standard_moisture,
                            nominal_speed,
                            variability,
                            headland,
                            headland_penalty,
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
                            run, child_seed, "yield_point", field_id, year, crop_name
                        )
                        attributes.update({
                            "yield_id": f"YP{year}_{field_index:03d}_{point_counter:08d}",
                            "pass_id": pass_id,
                            "timestamp": timestamp,
                            "timezone": timezone_label,
                            "heading": round(heading, 3),
                            "dry_yield": round(values["dry_yield"], 4),
                            "wet_yield": round(values["wet_yield"], 4),
                            "yield_unit": yield_unit,
                            "moisture_pct": round(values["moisture_pct"], 3),
                            "standard_moisture": standard_moisture,
                            "speed": round(values["speed"], 3),
                            "speed_unit": units.speed_unit,
                            "swath_width": swath_width_ft,
                            "distance_unit": units.distance_unit,
                            "logging_interval_sec": logging_interval,
                            "is_headland": headland,
                            "variability_level": variability,
                            "variability_multiplier": multiplier,
                            "latitude": round(point_wgs84.y(), 7),
                            "longitude": round(point_wgs84.x(), 7),
                        })
                        feature.setAttributes(
                            [attributes.get(name) for name in point_field_names]
                        )
                        if not point_writer.addFeature(feature):
                            raise QgsProcessingException(f"Could not write yield point for {field_id}")
                        samples.append((QgsPointXY(point), values))
                        point_counter += 1
                        manifest["counts"]["yield_points"] += 1
                        completed_work = (
                            manifest["counts"]["yield_points"]
                            + manifest["counts"]["surface_cells"]
                        )
                        if completed_work % 1000 == 0:
                            progress.update(
                                min(completed_work, estimated_work - 1),
                                f"{field_id} yield points",
                                completed_work,
                            )
                    elapsed_seconds += line.length() / max(0.01, nominal_speed_mps) + 45.0

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
                                        for key in ("dry_yield", "wet_yield", "moisture_pct", "speed")
                                    }
                                    method = "point_mean"
                                else:
                                    values = self._values(
                                        centroid,
                                        bbox,
                                        stable_seed(child_seed, "surface", row_index, column_index),
                                        field_pattern,
                                        minimum_yield,
                                        maximum_yield,
                                        minimum_moisture,
                                        maximum_moisture,
                                        standard_moisture,
                                        nominal_speed,
                                        variability,
                                        headland,
                                        headland_penalty,
                                        noise_scale=0.35,
                                    )
                                    method = "generated_centroid"
                                clipped.transform(to_source)
                                if not clipped.isMultipart():
                                    clipped.convertToMultiType()
                                feature = QgsFeature(surface_fields)
                                feature.setGeometry(clipped)
                                self._set_common(
                                    feature, run, child_seed, "yield_surface", field_id, year, crop_name
                                )
                                for name, value in {
                                    "cell_id": f"YSC{year}_{field_index:03d}_{cell_counter:07d}",
                                    "dry_yield": round(values["dry_yield"], 4),
                                    "wet_yield": round(values["wet_yield"], 4),
                                    "yield_unit": yield_unit,
                                    "moisture_pct": round(values["moisture_pct"], 3),
                                    "standard_moisture": standard_moisture,
                                    "speed": round(values["speed"], 3),
                                    "speed_unit": units.speed_unit,
                                    "is_headland": headland,
                                    "grid_size": surface_grid_size_ft,
                                    "distance_unit": units.distance_unit,
                                    "surface_method": method,
                                    "source_points": len(local),
                                    "heading": round(bearing, 3),
                                }.items():
                                    feature.setAttribute(name, value)
                                if not surface_writer.addFeature(feature):
                                    raise QgsProcessingException(
                                        f"Could not write yield surface cell for {field_id}"
                                    )
                                cell_counter += 1
                                manifest["counts"]["surface_cells"] += 1
                                completed_work = (
                                    manifest["counts"]["yield_points"]
                                    + manifest["counts"]["surface_cells"]
                                )
                                if completed_work % 1000 == 0:
                                    progress.update(
                                        min(completed_work, estimated_work - 1),
                                        f"{field_id} yield surface",
                                        completed_work,
                                    )
                            x += surface_grid_size_m
                            column_index += 1
                        y += surface_grid_size_m
                        row_index += 1
                completed_work = (
                    manifest["counts"]["yield_points"]
                    + manifest["counts"]["surface_cells"]
                )
                progress.update(
                    min(completed_work, estimated_work - 1),
                    f"{field_id} {year}",
                    completed_work,
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
                progress.update(
                    estimated_work,
                    "finished",
                    manifest["counts"]["yield_points"]
                    + manifest["counts"]["surface_cells"],
                    force=True,
                )
        except Exception as error:
            manifest["status"] = "incomplete"
            manifest["error"] = str(error)
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            raise

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        feedback.pushInfo(FAKE_WARNING)
        feedback.pushInfo(
            f"Created {manifest['counts']['yield_points']:,} yield points and "
            f"{manifest['counts']['surface_cells']:,} surface cells"
        )
        return {
            self.OUTPUT_FOLDER: str(run_folder),
            self.POINT_LAYER: str(point_path),
            self.SURFACE_LAYER: str(surface_path) if create_surface else "",
            self.MANIFEST: str(manifest_path),
        }
