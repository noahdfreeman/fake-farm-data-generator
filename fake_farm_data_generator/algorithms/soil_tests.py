# SPDX-License-Identifier: GPL-3.0-or-later
"""Create fake soil-test points and interpolated polygon-grid surfaces."""

from __future__ import annotations

import json
import math
import random
import re
from datetime import datetime
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
    idw_value,
    ordinary_kriging_weights,
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


class CreateFakeSoilTestsAlgorithm(QgsProcessingAlgorithm):
    """Generate deterministic fake soil samples and interpolated surfaces."""

    INPUT = "INPUT"
    UNIT_SYSTEM = "UNIT_SYSTEM"
    FIRST_YEAR = "FIRST_YEAR"
    INTERVAL = "INTERVAL"
    FINAL_YEAR = "FINAL_YEAR"
    PLACEMENT = "PLACEMENT"
    SAMPLE_DENSITY = "SAMPLE_DENSITY"
    BOUNDARY_SETBACK = "BOUNDARY_SETBACK"
    GRID_ROTATION = "GRID_ROTATION"
    GRID_OFFSET_X = "GRID_OFFSET_X"
    GRID_OFFSET_Y = "GRID_OFFSET_Y"
    SAMPLE_DEPTH = "SAMPLE_DEPTH"
    LAB_NAME = "LAB_NAME"
    FERTILITY_LEVEL = "FERTILITY_LEVEL"
    VARIABILITY_LEVEL = "VARIABILITY_LEVEL"
    P_UNIT = "P_UNIT"
    K_UNIT = "K_UNIT"
    SAMPLE_MONTH_DAY = "SAMPLE_MONTH_DAY"
    DATE_WINDOW = "DATE_WINDOW"
    CREATE_UNATTRIBUTED = "CREATE_UNATTRIBUTED"
    CREATE_SURFACE = "CREATE_SURFACE"
    SURFACE_GRID_SIZE = "SURFACE_GRID_SIZE"
    INTERPOLATION_METHOD = "INTERPOLATION_METHOD"
    IDW_POWER = "IDW_POWER"
    MAX_NEIGHBORS = "MAX_NEIGHBORS"
    KRIGING_MODEL = "KRIGING_MODEL"
    KRIGING_RANGE = "KRIGING_RANGE"
    KRIGING_NUGGET = "KRIGING_NUGGET"
    RANDOM_SEED = "RANDOM_SEED"
    OUTPUT_FORMATS = "OUTPUT_FORMATS"
    CREATE_REVIEW = "CREATE_REVIEW"
    REVIEW_MAX_FEATURES = "REVIEW_MAX_FEATURES"
    OUTPUT_DIR = "OUTPUT_DIR"

    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    POINT_LAYERS = "POINT_LAYERS"
    SURFACE_LAYERS = "SURFACE_LAYERS"
    MANIFEST = "MANIFEST"

    PLACEMENT_OPTIONS = ["Regular Grid", "Random"]
    FERTILITY_OPTIONS = ["Low", "Medium", "High"]
    VARIABILITY_OPTIONS = ["Low", "Medium", "High"]
    UNIT_OPTIONS = ["ppm", "lb/acre"]
    INTERPOLATION_OPTIONS = ["IDW", "Ordinary Kriging"]
    KRIGING_MODEL_OPTIONS = ["Spherical", "Exponential", "Gaussian"]
    NUTRIENTS = ["P", "K", "pH", "bpH", "OM", "CEC", "Ca", "Mg", "B", "Cu", "Fe", "Mn", "Zn"]

    # (minimum, maximum, mean, standard deviation)
    SOIL_RANGES = {
        "Low": {
            "P": (5, 20, 12, 4),
            "K": (50, 120, 85, 20),
            "pH": (5.2, 6.0, 5.6, 0.3),
            "bpH": (6.0, 6.5, 6.2, 0.2),
            "OM": (1.0, 2.5, 1.8, 0.4),
            "CEC": (5, 12, 8, 2),
            "Ca": (500, 1500, 1000, 300),
            "Mg": (50, 150, 100, 30),
            "B": (0.1, 0.5, 0.3, 0.1),
            "Cu": (0.5, 1.5, 1.0, 0.3),
            "Fe": (50, 150, 100, 30),
            "Mn": (10, 30, 20, 6),
            "Zn": (0.5, 1.5, 1.0, 0.3),
        },
        "Medium": {
            "P": (20, 50, 35, 10),
            "K": (120, 200, 160, 25),
            "pH": (6.0, 6.8, 6.4, 0.3),
            "bpH": (6.5, 7.0, 6.8, 0.2),
            "OM": (2.5, 4.0, 3.2, 0.5),
            "CEC": (12, 22, 17, 3),
            "Ca": (1500, 3000, 2200, 400),
            "Mg": (150, 400, 280, 70),
            "B": (0.5, 1.2, 0.8, 0.2),
            "Cu": (1.5, 3.0, 2.2, 0.5),
            "Fe": (80, 180, 130, 30),
            "Mn": (25, 60, 42, 10),
            "Zn": (1.5, 4.0, 2.8, 0.7),
        },
        "High": {
            "P": (50, 120, 80, 20),
            "K": (200, 400, 280, 50),
            "pH": (6.5, 7.2, 6.9, 0.2),
            "bpH": (6.8, 7.3, 7.0, 0.15),
            "OM": (3.5, 6.0, 4.5, 0.7),
            "CEC": (18, 35, 25, 5),
            "Ca": (2500, 5000, 3500, 600),
            "Mg": (350, 800, 500, 120),
            "B": (1.0, 2.0, 1.4, 0.3),
            "Cu": (2.5, 5.0, 3.5, 0.7),
            "Fe": (120, 300, 200, 50),
            "Mn": (50, 100, 70, 15),
            "Zn": (3.0, 10, 5.5, 1.5),
        },
    }

    # Dedicated fake lb/acre profiles; these are not represented as lab conversions.
    P_LB_AC_RANGES = {
        "Low": (10, 40, 24, 8),
        "Medium": (40, 100, 70, 20),
        "High": (100, 240, 160, 40),
    }
    K_LB_AC_RANGES = {
        "Low": (100, 240, 170, 40),
        "Medium": (240, 400, 320, 50),
        "High": (400, 800, 560, 100),
    }

    def tr(self, text):
        return QCoreApplication.translate("FakeFarmDataGenerator", text)

    def createInstance(self):
        return CreateFakeSoilTestsAlgorithm()

    def name(self):
        return "create_fake_soil_test_data"

    def displayName(self):
        return self.tr("Create Fake Soil Test Data")

    def group(self):
        return self.tr("Fake Farm Data Generator")

    def groupId(self):
        return "fake_farm_data_generator"

    def shortHelpString(self):
        return self.tr(
            "Creates clearly labeled fake soil-test points using a regular grid or "
            "deterministic random placement. Attributed runs can create an IDW or "
            "ordinary-kriging polygon-grid surface. Kriging supports spherical, "
            "exponential, and Gaussian variograms. Phosphorus and potassium may use "
            "ppm or dedicated fake lb/acre profiles. Outputs are not for agronomic decisions."
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
                self.FIRST_YEAR,
                self.tr("First sampling year"),
                QgsProcessingParameterNumber.Type.Integer,
                current_year,
                False,
                1900,
                2100,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.INTERVAL,
                self.tr("Sampling interval (years)"),
                QgsProcessingParameterNumber.Type.Integer,
                3,
                False,
                1,
                25,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.FINAL_YEAR,
                self.tr("Final sampling year (blank = first year only)"),
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PLACEMENT,
                self.tr("Point placement"),
                self.PLACEMENT_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SAMPLE_DENSITY,
                self.tr("Sample density (acres/point Imperial; ha/point Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                2.5,
                False,
                0.25,
                50.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.BOUNDARY_SETBACK,
                self.tr("Sample-point setback from field boundary (ft Imperial; m Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                150.0,
                False,
                0.0,
                5000.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRID_ROTATION,
                self.tr("Regular-grid rotation (degrees)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                -180.0,
                180.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRID_OFFSET_X,
                self.tr("Regular-grid X offset (% of spacing)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                -100.0,
                100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.GRID_OFFSET_Y,
                self.tr("Regular-grid Y offset (% of spacing)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                -100.0,
                100.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SAMPLE_DEPTH, self.tr("Sample depth"), "0-8 inches"
            )
        )
        self.addParameter(
            QgsProcessingParameterString(self.LAB_NAME, self.tr("Lab name"), "Test Lab")
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.FERTILITY_LEVEL,
                self.tr("Fertility level"),
                self.FERTILITY_OPTIONS,
                False,
                1,
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
            QgsProcessingParameterEnum(
                self.P_UNIT, self.tr("Phosphorus unit"), self.UNIT_OPTIONS, False, 0
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.K_UNIT, self.tr("Potassium unit"), self.UNIT_OPTIONS, False, 0
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.SAMPLE_MONTH_DAY,
                self.tr("Default sample date (MM-DD)"),
                "11-10",
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
            QgsProcessingParameterBoolean(
                self.CREATE_UNATTRIBUTED,
                self.tr("Create unattributed points (no nutrient columns)"),
                False,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.CREATE_SURFACE,
                self.tr("Create interpolated polygon-grid surface"),
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
            QgsProcessingParameterEnum(
                self.INTERPOLATION_METHOD,
                self.tr("Surface interpolation method"),
                self.INTERPOLATION_OPTIONS,
                False,
                1,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.IDW_POWER,
                self.tr("IDW power"),
                QgsProcessingParameterNumber.Type.Double,
                2.0,
                False,
                0.1,
                10.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_NEIGHBORS,
                self.tr("Maximum interpolation neighbors"),
                QgsProcessingParameterNumber.Type.Integer,
                12,
                False,
                1,
                100,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.KRIGING_MODEL,
                self.tr("Kriging variogram model"),
                self.KRIGING_MODEL_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KRIGING_RANGE,
                self.tr("Kriging practical range (ft Imperial; m Metric; 0 = automatic)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                0.0,
                100000.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KRIGING_NUGGET,
                self.tr("Kriging relative nugget (0-1)"),
                QgsProcessingParameterNumber.Type.Double,
                0.0,
                False,
                0.0,
                1.0,
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
        self.addOutput(QgsProcessingOutputString(self.POINT_LAYERS, "Point layers"))
        self.addOutput(QgsProcessingOutputString(self.SURFACE_LAYERS, "Surface layers"))
        self.addOutput(QgsProcessingOutputString(self.MANIFEST, "Run manifest"))

    @staticmethod
    def _safe_name(text, fallback):
        cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text or "")).strip("_")
        return cleaned or fallback

    @staticmethod
    def _clamp(value, bounds):
        return max(bounds[0], min(bounds[1], value))

    def _ranges(self, fertility, p_unit, k_unit):
        ranges = dict(self.SOIL_RANGES[fertility])
        if p_unit in {"lb/acre", "kg/ha"}:
            ranges["P"] = self.P_LB_AC_RANGES[fertility]
        if k_unit in {"lb/acre", "kg/ha"}:
            ranges["K"] = self.K_LB_AC_RANGES[fertility]
        if p_unit == "kg/ha":
            ranges["P"] = tuple(value * 1.120851156 for value in ranges["P"])
        if k_unit == "kg/ha":
            ranges["K"] = tuple(value * 1.120851156 for value in ranges["K"])
        return ranges

    @staticmethod
    def _selected_or_all(layer):
        if layer.selectedFeatureCount() > 0:
            return list(layer.selectedFeatures()), True
        return list(layer.getFeatures()), False

    @staticmethod
    def _working_crs(source_crs, features, transform_context):
        centroid = features[0].geometry().centroid()
        if centroid.isEmpty():
            raise QgsProcessingException("Could not determine a centroid for the first field")
        point = centroid.asPoint()
        if source_crs.authid() != "EPSG:4326":
            to_wgs84 = QgsCoordinateTransform(
                source_crs, QgsCoordinateReferenceSystem("EPSG:4326"), transform_context
            )
            point = to_wgs84.transform(point)
        zone = max(1, min(60, int((point.x() + 180.0) / 6.0) + 1))
        epsg = (32600 if point.y() >= 0 else 32700) + zone
        return QgsCoordinateReferenceSystem(f"EPSG:{epsg}")

    @staticmethod
    def _writer(path, fields, crs, geometry_type, layer_name):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        options.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        writer = QgsVectorFileWriter.create(
            str(path),
            fields,
            geometry_type,
            crs,
            QgsProject.instance().transformContext(),
            options,
        )
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise QgsProcessingException(
                f"Could not create output GeoPackage {path}: {writer.errorMessage()}"
            )
        return writer

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

    def _point_fields(self, attributed):
        fields = self._common_fields()
        for name, variant in (
            ("sample_id", QVariant.String),
            ("sample_date", QVariant.String),
            ("sample_depth", QVariant.String),
            ("lab_name", QVariant.String),
            ("sample_density", QVariant.Double),
            ("density_unit", QVariant.String),
            ("boundary_setback", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("fertility_level", QVariant.String),
            ("variability_level", QVariant.String),
            ("variability_multiplier", QVariant.Double),
            ("placement_mode", QVariant.String),
            ("p_unit", QVariant.String),
            ("k_unit", QVariant.String),
            ("latitude", QVariant.Double),
            ("longitude", QVariant.Double),
        ):
            fields.append(QgsField(name, variant))
        if attributed:
            for nutrient in self.NUTRIENTS:
                fields.append(QgsField(nutrient, QVariant.Double))
        return fields

    def _surface_fields(self):
        fields = self._common_fields()
        for name, variant in (
            ("cell_id", QVariant.String),
            ("grid_size", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("surface_method", QVariant.String),
            ("idw_power", QVariant.Double),
            ("max_neighbors", QVariant.Int),
            ("variogram_model", QVariant.String),
            ("kriging_range", QVariant.Double),
            ("range_mode", QVariant.String),
            ("nugget_ratio", QVariant.Double),
            ("kriging_variance", QVariant.Double),
            ("kriging_fallback", QVariant.Bool),
            ("source_points", QVariant.Int),
            ("placement_mode", QVariant.String),
            ("variability_level", QVariant.String),
            ("variability_multiplier", QVariant.Double),
            ("p_unit", QVariant.String),
            ("k_unit", QVariant.String),
        ):
            fields.append(QgsField(name, variant))
        for nutrient in self.NUTRIENTS:
            fields.append(QgsField(nutrient, QVariant.Double))
        return fields

    @staticmethod
    def _set_common(feature, run, child_seed, data_type, field_id, year):
        identity = run["field_identities"].get(
            field_id,
            {"field_id": field_id, "field_name": field_id, "farm_name": "", "grower_name": ""},
        )
        values = {
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
        for name, value in values.items():
            feature.setAttribute(name, value)

    @staticmethod
    def _regular_grid_points(geometry, spacing, rotation_degrees, offset_x, offset_y):
        bbox = geometry.boundingBox()
        center = bbox.center()
        radius = math.hypot(bbox.width(), bbox.height()) / 2.0 + spacing
        angle = math.radians(rotation_degrees)
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        start_u = -radius + spacing / 2.0 + spacing * offset_x / 100.0
        start_v = -radius + spacing / 2.0 + spacing * offset_y / 100.0
        points = []
        u = start_u
        while u <= radius:
            v = start_v
            while v <= radius:
                x = center.x() + u * cos_angle - v * sin_angle
                y = center.y() + u * sin_angle + v * cos_angle
                point = QgsPointXY(x, y)
                if geometry.contains(QgsGeometry.fromPointXY(point)):
                    points.append(point)
                v += spacing
            u += spacing
        if not points:
            point = geometry.pointOnSurface().asPoint()
            points.append(QgsPointXY(point))
        return points

    @staticmethod
    def _random_points(geometry, target, rng):
        bbox = geometry.boundingBox()
        points = []
        attempts = 0
        maximum_attempts = max(1000, target * 500)
        while len(points) < target and attempts < maximum_attempts:
            point = QgsPointXY(
                rng.uniform(bbox.xMinimum(), bbox.xMaximum()),
                rng.uniform(bbox.yMinimum(), bbox.yMaximum()),
            )
            if geometry.contains(QgsGeometry.fromPointXY(point)):
                points.append(point)
            attempts += 1
        if not points:
            point = geometry.pointOnSurface().asPoint()
            points.append(QgsPointXY(point))
        if len(points) < target:
            raise QgsProcessingException(
                f"Could create only {len(points)} of {target} requested random soil points"
            )
        return points

    def _field_values(self, ranges, rng, multiplier):
        values = {}
        for nutrient, bounds in ranges.items():
            minimum, maximum, mean, standard_deviation = bounds
            values[nutrient] = self._clamp(
                rng.gauss(mean, standard_deviation * multiplier),
                (minimum, maximum),
            )
        return values

    def _point_values(self, ranges, base_values, rng, multiplier):
        values = {}
        for nutrient, bounds in ranges.items():
            minimum, maximum, _mean, standard_deviation = bounds
            values[nutrient] = self._clamp(
                rng.gauss(base_values[nutrient], standard_deviation * multiplier * 0.2),
                (minimum, maximum),
            )
        return values

    @staticmethod
    def _month_day(value):
        match = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})\s*", value or "")
        if not match:
            raise QgsProcessingException("Default sample date must use MM-DD")
        month, day = int(match.group(1)), int(match.group(2))
        try:
            datetime(2000, month, day)
        except ValueError as error:
            raise QgsProcessingException(f"Invalid default sample date: {error}") from error
        return month, day

    @staticmethod
    def _years(first_year, interval, final_text):
        if not str(final_text or "").strip():
            return [first_year]
        try:
            final_year = int(str(final_text).strip())
        except ValueError as error:
            raise QgsProcessingException("Final sampling year must be a whole year") from error
        if final_year < first_year:
            raise QgsProcessingException("Final sampling year cannot precede first year")
        years = list(range(first_year, final_year + 1, interval))
        if len(years) > 10:
            raise QgsProcessingException("A soil-test run may contain no more than 10 years")
        return years

    @staticmethod
    def _rectangle(x_min, y_min, x_max, y_max):
        ring = [
            QgsPointXY(x_min, y_min),
            QgsPointXY(x_max, y_min),
            QgsPointXY(x_max, y_max),
            QgsPointXY(x_min, y_max),
            QgsPointXY(x_min, y_min),
        ]
        return QgsGeometry.fromPolygonXY([ring])

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException("Invalid field-boundary layer")
        features, used_selection = self._selected_or_all(source)
        if not features:
            raise QgsProcessingException("No field polygons were available to process")
        if len(features) > 20:
            raise QgsProcessingException("No more than 20 field polygons may be processed")

        units = unit_system(self.parameterAsEnum(parameters, self.UNIT_SYSTEM, context))
        first_year = self.parameterAsInt(parameters, self.FIRST_YEAR, context)
        interval = self.parameterAsInt(parameters, self.INTERVAL, context)
        final_text = self.parameterAsString(parameters, self.FINAL_YEAR, context)
        years = self._years(first_year, interval, final_text)
        placement = self.PLACEMENT_OPTIONS[
            self.parameterAsEnum(parameters, self.PLACEMENT, context)
        ]
        density_acres = self.parameterAsDouble(parameters, self.SAMPLE_DENSITY, context)
        boundary_setback = self.parameterAsDouble(
            parameters, self.BOUNDARY_SETBACK, context
        )
        grid_rotation = self.parameterAsDouble(parameters, self.GRID_ROTATION, context)
        grid_offset_x = self.parameterAsDouble(parameters, self.GRID_OFFSET_X, context)
        grid_offset_y = self.parameterAsDouble(parameters, self.GRID_OFFSET_Y, context)
        sample_depth = self.parameterAsString(parameters, self.SAMPLE_DEPTH, context)
        lab_name = self.parameterAsString(parameters, self.LAB_NAME, context)
        fertility = self.FERTILITY_OPTIONS[
            self.parameterAsEnum(parameters, self.FERTILITY_LEVEL, context)
        ]
        variability = self.VARIABILITY_OPTIONS[
            self.parameterAsEnum(parameters, self.VARIABILITY_LEVEL, context)
        ]
        multiplier = VARIABILITY_MULTIPLIERS[variability]
        p_unit = self.UNIT_OPTIONS[self.parameterAsEnum(parameters, self.P_UNIT, context)]
        k_unit = self.UNIT_OPTIONS[self.parameterAsEnum(parameters, self.K_UNIT, context)]
        if units.metric:
            p_unit = "kg/ha" if p_unit == "lb/acre" else p_unit
            k_unit = "kg/ha" if k_unit == "lb/acre" else k_unit
            if sample_depth == "0-8 inches":
                sample_depth = "0-20 cm"
        month, day = self._month_day(
            self.parameterAsString(parameters, self.SAMPLE_MONTH_DAY, context)
        )
        date_window = self.parameterAsInt(parameters, self.DATE_WINDOW, context)
        unattributed = self.parameterAsBool(parameters, self.CREATE_UNATTRIBUTED, context)
        create_surface = self.parameterAsBool(parameters, self.CREATE_SURFACE, context)
        if unattributed and create_surface:
            create_surface = False
            feedback.pushWarning(
                "Interpolated soil surface was disabled because unattributed mode has no nutrient values"
            )
        surface_grid_size_ft = self.parameterAsDouble(
            parameters, self.SURFACE_GRID_SIZE, context
        )
        interpolation_method = self.INTERPOLATION_OPTIONS[
            self.parameterAsEnum(parameters, self.INTERPOLATION_METHOD, context)
        ]
        idw_power = self.parameterAsDouble(parameters, self.IDW_POWER, context)
        max_neighbors = self.parameterAsInt(parameters, self.MAX_NEIGHBORS, context)
        kriging_model = self.KRIGING_MODEL_OPTIONS[
            self.parameterAsEnum(parameters, self.KRIGING_MODEL, context)
        ]
        requested_kriging_range_ft = self.parameterAsDouble(
            parameters, self.KRIGING_RANGE, context
        )
        kriging_nugget = self.parameterAsDouble(
            parameters, self.KRIGING_NUGGET, context
        )
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

        transform_context = context.transformContext()
        source_crs = source.crs()
        working_crs = self._working_crs(source_crs, features, transform_context)
        to_working = QgsCoordinateTransform(source_crs, working_crs, transform_context)
        to_source = QgsCoordinateTransform(working_crs, source_crs, transform_context)
        to_wgs84 = QgsCoordinateTransform(
            working_crs, QgsCoordinateReferenceSystem("EPSG:4326"), transform_context
        )
        ranges = self._ranges(fertility, p_unit, k_unit)
        area_per_point_m2 = density_acres * (10000.0 if units.metric else 4046.8564224)
        spacing_m = math.sqrt(area_per_point_m2)
        boundary_setback_m = units.distance_to_meters(boundary_setback)
        surface_grid_size_m = units.distance_to_meters(surface_grid_size_ft)
        kriging_range_m = (
            units.distance_to_meters(requested_kriging_range_ft)
            if requested_kriging_range_ft > 0.0
            else spacing_m * 3.0
        )
        effective_kriging_range_ft = kriging_range_m / units.distance_to_meters(1.0)
        kriging_range_mode = "User" if requested_kriging_range_ft > 0.0 else "Automatic"

        total_area_square_meters = 0.0
        for source_feature in features:
            geometry = QgsGeometry(source_feature.geometry())
            if geometry.isEmpty():
                continue
            geometry.transform(to_working)
            total_area_square_meters += max(0.0, geometry.area())
        total_area_acres = total_area_square_meters / 4046.8564224
        if total_area_acres > 5000.0 + 0.01:
            raise QgsProcessingException(
                f"Selected fields total {total_area_acres:,.1f} acres; the v1 limit is 5,000 acres"
            )
        total_area_display = units.area_from_square_meters(total_area_square_meters)
        estimated_points = max(1, int(math.ceil(total_area_display / density_acres))) * len(years)
        estimated_surface_cells = (
            int(math.ceil(total_area_square_meters / (surface_grid_size_m**2)))
            * len(years)
            if create_surface
            else 0
        )
        feedback.pushInfo(
            f"Preflight estimate: {estimated_points:,} soil points and approximately "
            f"{estimated_surface_cells:,} surface cells"
        )
        if create_surface:
            if interpolation_method == "Ordinary Kriging":
                feedback.pushInfo(
                    f"Surface interpolation: ordinary kriging, {kriging_model.lower()} "
                    f"variogram, {effective_kriging_range_ft:,.1f} {units.distance_unit} "
                    f"{kriging_range_mode.lower()} range, nugget {kriging_nugget:.3f}"
                )
            else:
                feedback.pushInfo(
                    f"Surface interpolation: IDW, power {idw_power:g}, "
                    f"maximum {max_neighbors} neighbors"
                )
        if estimated_points + estimated_surface_cells >= 100_000:
            feedback.pushWarning(
                "This run may take a while. QGIS must remain open until processing finishes."
            )

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_folder = parent_output / f"Fake_Farm_Data_{run_id}"
        run_folder.mkdir(parents=False, exist_ok=False)
        run = {
            "run_id": run_id,
            "created_at": created_at,
            "master_seed": master_seed,
            "unit_system": units.name,
            "review_max_features": review_max_features,
            "output_formats": output_formats,
            "field_identities": {
                feature_field_id(feature, index): feature_field_identity(feature, index)
                for index, feature in enumerate(features, start=1)
            },
        }

        point_paths = []
        surface_paths = []
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
            "total_area_hectares": round(total_area_square_meters / 10000.0, 4),
            "unit_system": units.name,
            "review_max_features": review_max_features,
            "years": years,
            "soil": {
                "placement_mode": placement,
                "sample_density_acres": density_acres,
                "sample_density": density_acres,
                "density_unit": f"{units.area_unit}/point",
                "boundary_setback": boundary_setback,
                "distance_unit": units.distance_unit,
                "fertility_level": fertility,
                "variability_level": variability,
                "variability_multiplier": multiplier,
                "p_unit": p_unit,
                "k_unit": k_unit,
                "surface_requested": self.parameterAsBool(
                    parameters, self.CREATE_SURFACE, context
                ),
                "surface_created": create_surface,
                "interpolation_method": interpolation_method,
                "idw_power": idw_power,
                "max_neighbors": max_neighbors,
                "kriging_variogram_model": kriging_model,
                "kriging_range_feet": round(effective_kriging_range_ft, 3),
                "kriging_range": round(effective_kriging_range_ft, 3),
                "distance_unit": units.distance_unit,
                "kriging_range_mode": kriging_range_mode,
                "kriging_nugget_ratio": kriging_nugget,
            },
            "outputs": [],
            "estimates": {
                "soil_points": estimated_points,
                "soil_surface_cells": estimated_surface_cells,
            },
            "counts": {
                "soil_points": 0,
                "soil_surface_cells": 0,
                "kriging_fallback_cells": 0,
            },
        }
        manifest_path = run_folder / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        try:
            fallback_warning_sent = False
            total_work = max(1, len(years) * len(features))
            progress = ProgressReporter(feedback, total_work, "Soil tests")
            completed_work = 0
            for year in years:
                if feedback.isCanceled():
                    manifest["status"] = "incomplete"
                    break
                year_folder = run_folder / str(year)
                year_folder.mkdir(exist_ok=True)
                point_path = year_folder / f"fake_soil_tests_{year}.gpkg"
                point_fields = self._point_fields(not unattributed)
                point_writer = self._writer(
                    point_path,
                    point_fields,
                    source_crs,
                    QgsWkbTypes.Type.Point,
                    f"fake_soil_tests_{year}",
                )
                surface_writer = None
                surface_path = year_folder / f"fake_soil_surface_{year}.gpkg"
                surface_fields = None
                if create_surface:
                    surface_fields = self._surface_fields()
                    surface_writer = self._writer(
                        surface_path,
                        surface_fields,
                        source_crs,
                        QgsWkbTypes.Type.MultiPolygon,
                        f"fake_soil_surface_{year}",
                    )

                sample_counter = 1
                cell_counter = 1
                operation_seed = stable_seed(master_seed, "soil", year, "date")
                sample_date = deterministic_operation_date(
                    year, month, day, date_window, operation_seed
                ).isoformat()

                for field_index, source_feature in enumerate(features, start=1):
                    if feedback.isCanceled():
                        manifest["status"] = "incomplete"
                        break
                    field_id = feature_field_id(source_feature, field_index)
                    geometry = QgsGeometry(source_feature.geometry())
                    if geometry.isEmpty():
                        feedback.pushWarning(f"Skipping empty geometry for {field_id}")
                        completed_work += 1
                        continue
                    geometry.transform(to_working)
                    if geometry.isEmpty() or geometry.area() <= 0:
                        feedback.pushWarning(f"Skipping invalid projected geometry for {field_id}")
                        completed_work += 1
                        continue
                    area_acres = geometry.area() / 4046.8564224
                    area_display = units.area_from_square_meters(geometry.area())
                    sampling_geometry = (
                        geometry.buffer(-boundary_setback_m, 8)
                        if boundary_setback_m > 0
                        else QgsGeometry(geometry)
                    )
                    if sampling_geometry.isEmpty() or sampling_geometry.area() <= 0:
                        raise QgsProcessingException(
                            f"{field_id} is too narrow for the {boundary_setback:g} "
                            f"{units.distance_unit} soil-test boundary setback; reduce the setback"
                        )
                    child_seed = stable_seed(master_seed, field_id, year, "soil")
                    # Reproducible fake sampling placement; not cryptography.
                    rng = random.Random(child_seed)  # nosec B311
                    target_points = max(1, int(math.ceil(area_display / density_acres)))
                    if placement == "Regular Grid":
                        points = self._regular_grid_points(
                            sampling_geometry,
                            spacing_m,
                            grid_rotation,
                            grid_offset_x,
                            grid_offset_y,
                        )
                    else:
                        points = self._random_points(
                            sampling_geometry, target_points, rng
                        )

                    feedback.pushInfo(
                        f"{field_id} {year}: {area_display:.1f} {units.area_unit}; "
                        f"creating {len(points)} {placement.lower()} points"
                    )
                    base_values = None if unattributed else self._field_values(
                        ranges, rng, multiplier
                    )
                    field_samples = []
                    for point in points:
                        values = None if unattributed else self._point_values(
                            ranges, base_values, rng, multiplier
                        )
                        point_source = to_source.transform(point)
                        point_wgs84 = to_wgs84.transform(point)
                        feature = QgsFeature(point_fields)
                        feature.setGeometry(QgsGeometry.fromPointXY(point_source))
                        self._set_common(
                            feature, run, child_seed, "soil_test_point", field_id, year
                        )
                        feature.setAttribute(
                            "sample_id", f"S{year}_{field_index:03d}_{sample_counter:05d}"
                        )
                        feature.setAttribute("sample_date", sample_date)
                        feature.setAttribute("sample_depth", sample_depth)
                        feature.setAttribute("lab_name", lab_name)
                        feature.setAttribute("sample_density", density_acres)
                        feature.setAttribute("density_unit", f"{units.area_unit}/point")
                        feature.setAttribute("boundary_setback", boundary_setback)
                        feature.setAttribute("distance_unit", units.distance_unit)
                        feature.setAttribute("fertility_level", fertility)
                        feature.setAttribute("variability_level", variability)
                        feature.setAttribute("variability_multiplier", multiplier)
                        feature.setAttribute("placement_mode", placement)
                        feature.setAttribute("p_unit", p_unit)
                        feature.setAttribute("k_unit", k_unit)
                        feature.setAttribute("latitude", round(point_wgs84.y(), 7))
                        feature.setAttribute("longitude", round(point_wgs84.x(), 7))
                        if values is not None:
                            for nutrient, value in values.items():
                                feature.setAttribute(nutrient, round(value, 3))
                            field_samples.append((point.x(), point.y(), values))
                        if not point_writer.addFeature(feature):
                            raise QgsProcessingException(
                                f"Could not write soil point for {field_id} in {year}"
                            )
                        sample_counter += 1
                        manifest["counts"]["soil_points"] += 1

                    if create_surface and field_samples:
                        bbox = geometry.boundingBox()
                        y = bbox.yMinimum()
                        while y < bbox.yMaximum():
                            x = bbox.xMinimum()
                            while x < bbox.xMaximum():
                                cell = self._rectangle(
                                    x,
                                    y,
                                    min(x + surface_grid_size_m, bbox.xMaximum()),
                                    min(y + surface_grid_size_m, bbox.yMaximum()),
                                )
                                clipped = cell.intersection(geometry)
                                if not clipped.isEmpty() and clipped.area() > 0.001:
                                    centroid = clipped.centroid().asPoint()
                                    interpolated = {}
                                    contributing = 0
                                    kriging_variance = None
                                    kriging_fallback = False
                                    if interpolation_method == "Ordinary Kriging":
                                        try:
                                            indexes, weights, kriging_variance = (
                                                ordinary_kriging_weights(
                                                    (
                                                        (sample_x, sample_y)
                                                        for sample_x, sample_y, _values in field_samples
                                                    ),
                                                    centroid.x(),
                                                    centroid.y(),
                                                    kriging_model,
                                                    kriging_range_m,
                                                    kriging_nugget,
                                                    max_neighbors,
                                                )
                                            )
                                            contributing = len(indexes)
                                            for nutrient in self.NUTRIENTS:
                                                interpolated[nutrient] = sum(
                                                    weights[position]
                                                    * field_samples[index][2][nutrient]
                                                    for position, index in enumerate(indexes)
                                                )
                                        except ValueError as error:
                                            kriging_fallback = True
                                            manifest["counts"]["kriging_fallback_cells"] += 1
                                            if not fallback_warning_sent:
                                                feedback.pushWarning(
                                                    "One or more kriging systems were singular; "
                                                    f"those cells use IDW fallback. First error: {error}"
                                                )
                                                fallback_warning_sent = True
                                    if interpolation_method == "IDW" or kriging_fallback:
                                        for nutrient in self.NUTRIENTS:
                                            value, used = idw_value(
                                                (
                                                    (sx, sy, values[nutrient])
                                                    for sx, sy, values in field_samples
                                                ),
                                                centroid.x(),
                                                centroid.y(),
                                                idw_power,
                                                max_neighbors,
                                            )
                                            interpolated[nutrient] = value
                                            contributing = max(contributing, used)
                                    clipped.transform(to_source)
                                    if not clipped.isMultipart():
                                        clipped.convertToMultiType()
                                    surface_feature = QgsFeature(surface_fields)
                                    surface_feature.setGeometry(clipped)
                                    self._set_common(
                                        surface_feature,
                                        run,
                                        child_seed,
                                        "soil_test_surface",
                                        field_id,
                                        year,
                                    )
                                    surface_feature.setAttribute(
                                        "cell_id", f"SC{year}_{field_index:03d}_{cell_counter:06d}"
                                    )
                                    surface_feature.setAttribute(
                                        "grid_size", surface_grid_size_ft
                                    )
                                    surface_feature.setAttribute(
                                        "distance_unit", units.distance_unit
                                    )
                                    surface_feature.setAttribute(
                                        "surface_method", interpolation_method
                                    )
                                    surface_feature.setAttribute(
                                        "idw_power",
                                        idw_power
                                        if interpolation_method == "IDW" or kriging_fallback
                                        else None,
                                    )
                                    surface_feature.setAttribute(
                                        "max_neighbors", max_neighbors
                                    )
                                    surface_feature.setAttribute(
                                        "variogram_model",
                                        kriging_model
                                        if interpolation_method == "Ordinary Kriging"
                                        else None,
                                    )
                                    surface_feature.setAttribute(
                                        "kriging_range",
                                        effective_kriging_range_ft
                                        if interpolation_method == "Ordinary Kriging"
                                        else None,
                                    )
                                    surface_feature.setAttribute(
                                        "range_mode",
                                        kriging_range_mode
                                        if interpolation_method == "Ordinary Kriging"
                                        else None,
                                    )
                                    surface_feature.setAttribute(
                                        "nugget_ratio",
                                        kriging_nugget
                                        if interpolation_method == "Ordinary Kriging"
                                        else None,
                                    )
                                    surface_feature.setAttribute(
                                        "kriging_variance",
                                        kriging_variance,
                                    )
                                    surface_feature.setAttribute(
                                        "kriging_fallback", kriging_fallback
                                    )
                                    surface_feature.setAttribute(
                                        "source_points", contributing
                                    )
                                    surface_feature.setAttribute(
                                        "placement_mode", placement
                                    )
                                    surface_feature.setAttribute(
                                        "variability_level", variability
                                    )
                                    surface_feature.setAttribute(
                                        "variability_multiplier", multiplier
                                    )
                                    surface_feature.setAttribute("p_unit", p_unit)
                                    surface_feature.setAttribute("k_unit", k_unit)
                                    for nutrient, value in interpolated.items():
                                        surface_feature.setAttribute(
                                            nutrient,
                                            round(self._clamp(value, ranges[nutrient]), 3),
                                        )
                                    if not surface_writer.addFeature(surface_feature):
                                        raise QgsProcessingException(
                                            f"Could not write soil surface cell for {field_id} in {year}"
                                        )
                                    cell_counter += 1
                                    manifest["counts"]["soil_surface_cells"] += 1
                                x += surface_grid_size_m
                            y += surface_grid_size_m

                    completed_work += 1
                    progress.update(
                        completed_work,
                        f"{field_id} {year}",
                        manifest["counts"]["soil_points"]
                        + manifest["counts"]["soil_surface_cells"],
                        force=True,
                    )

                del point_writer
                point_paths.append(str(point_path))
                manifest["outputs"].append(str(point_path.relative_to(run_folder)))
                if surface_writer is not None:
                    del surface_writer
                    surface_paths.append(str(surface_path))
                    manifest["outputs"].append(str(surface_path.relative_to(run_folder)))
                if feedback.isCanceled():
                    break

            if manifest["status"] == "running":
                write_gpkg_run_metadata(point_paths + surface_paths, manifest)
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
            f"Created {manifest['counts']['soil_points']:,} soil points and "
            f"{manifest['counts']['soil_surface_cells']:,} surface cells"
        )
        if manifest["counts"]["kriging_fallback_cells"]:
            feedback.pushWarning(
                f"{manifest['counts']['kriging_fallback_cells']:,} kriging cells used "
                "the documented IDW fallback because their local kriging system was singular"
            )
        return {
            self.OUTPUT_FOLDER: str(run_folder),
            self.POINT_LAYERS: ";".join(point_paths),
            self.SURFACE_LAYERS: ";".join(surface_paths),
            self.MANIFEST: str(manifest_path),
        }
