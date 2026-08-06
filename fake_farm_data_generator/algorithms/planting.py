# SPDX-License-Identifier: GPL-3.0-or-later
"""Create deterministic fake planting logs and polygon-grid surfaces."""

from __future__ import annotations

import json
import math
import random
import re
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
    crop_provenance_from_json,
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


class CreateFakePlantingAlgorithm(QgsProcessingAlgorithm):
    """Generate fake planter-center logs, row-unit logs, and grid surfaces."""

    INPUT = "INPUT"
    UNIT_SYSTEM = "UNIT_SYSTEM"
    CROP_YEAR = "CROP_YEAR"
    CROP_NAME = "CROP_NAME"
    CROP_PROVENANCE_JSON = "CROP_PROVENANCE_JSON"
    POINT_OUTPUT = "POINT_OUTPUT"
    PLANTER_WIDTH = "PLANTER_WIDTH"
    ROW_UNITS = "ROW_UNITS"
    ROW_SPACING = "ROW_SPACING"
    TARGET_POPULATION = "TARGET_POPULATION"
    MIN_POPULATION = "MIN_POPULATION"
    MAX_POPULATION = "MAX_POPULATION"
    SEED_DEPTH = "SEED_DEPTH"
    NOMINAL_SPEED = "NOMINAL_SPEED"
    LOGGING_INTERVAL = "LOGGING_INTERVAL"
    HEADLAND_PASSES = "HEADLAND_PASSES"
    DIRECTION_MODE = "DIRECTION_MODE"
    MANUAL_BEARING = "MANUAL_BEARING"
    PLANTING_MONTH_DAY = "PLANTING_MONTH_DAY"
    DATE_WINDOW = "DATE_WINDOW"
    TIMEZONE = "TIMEZONE"
    VARIABILITY_LEVEL = "VARIABILITY_LEVEL"
    CREATE_SURFACE = "CREATE_SURFACE"
    SURFACE_GRID_SIZE = "SURFACE_GRID_SIZE"
    SURFACE_ATTRIBUTES = "SURFACE_ATTRIBUTES"
    RANDOM_SEED = "RANDOM_SEED"
    OUTPUT_FORMATS = "OUTPUT_FORMATS"
    CREATE_REVIEW = "CREATE_REVIEW"
    REVIEW_MAX_FEATURES = "REVIEW_MAX_FEATURES"
    OUTPUT_DIR = "OUTPUT_DIR"

    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    CENTER_LAYER = "CENTER_LAYER"
    ROW_LAYER = "ROW_LAYER"
    SURFACE_LAYER = "SURFACE_LAYER"
    MANIFEST = "MANIFEST"

    POINT_OUTPUT_OPTIONS = ["Planter Center", "Row Units", "Both"]
    DIRECTION_OPTIONS = ["Automatic", "Manual"]
    VARIABILITY_OPTIONS = ["Low", "Medium", "High"]
    SURFACE_ATTRIBUTE_OPTIONS = [
        "Population",
        "Speed",
        "Seed Spacing",
        "Seed Depth",
        "Singulation",
        "Spacing Quality",
        "Skips",
        "Ride Quality",
        "Ground Contact",
        "Furrow Moisture",
        "Furrow Temperature",
        "Uniform Furrow",
        "Clean Furrow",
    ]
    SURFACE_FIELD_MAP = {
        "Population": "population",
        "Speed": "speed",
        "Seed Spacing": "seed_spacing",
        "Seed Depth": "seed_depth",
        "Singulation": "singulation_pct",
        "Spacing Quality": "spacing_quality_pct",
        "Skips": "skips_pct",
        "Ride Quality": "ride_quality_pct",
        "Ground Contact": "ground_contact_pct",
        "Furrow Moisture": "furrow_moisture_pct",
        "Furrow Temperature": "furrow_temperature",
        "Uniform Furrow": "uniform_furrow_pct",
        "Clean Furrow": "clean_furrow_pct",
    }

    def tr(self, text):
        return QCoreApplication.translate("FakeFarmDataGenerator", text)

    def createInstance(self):
        return CreateFakePlantingAlgorithm()

    def name(self):
        return "create_fake_planting_data"

    def displayName(self):
        return self.tr("Create Fake Planting Data")

    def group(self):
        return self.tr("Fake Farm Data Generator")

    def groupId(self):
        return "fake_farm_data_generator"

    def shortHelpString(self):
        return self.tr(
            "Creates clearly labeled fake planter-center and/or row-unit log points "
            "plus an optional clipped polygon-grid surface. Passes, timestamps, "
            "population, speed, seed spacing, depth, planter-quality metrics, furrow "
            "conditions, headlands, and row-unit variation are deterministic for a fixed "
            "seed. Outputs are not for agronomic decisions."
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
                self.UNIT_SYSTEM,
                self.tr("Unit system"),
                UNIT_SYSTEM_OPTIONS,
                False,
                0,
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
            QgsProcessingParameterString(self.CROP_NAME, self.tr("Crop name"), "Corn")
        )
        provenance_parameter = QgsProcessingParameterString(
            self.CROP_PROVENANCE_JSON,
            self.tr("Crop provenance JSON (advanced)"),
            "",
            False,
            True,
        )
        self.addParameter(provenance_parameter)
        self.addParameter(
            QgsProcessingParameterEnum(
                self.POINT_OUTPUT,
                self.tr("Point records to create"),
                self.POINT_OUTPUT_OPTIONS,
                False,
                0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.PLANTER_WIDTH,
                self.tr("Planter width (ft Imperial; m Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                40.0,
                False,
                1.0,
                200.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROW_UNITS,
                self.tr("Number of row units"),
                QgsProcessingParameterNumber.Type.Integer,
                16,
                False,
                1,
                120,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.ROW_SPACING,
                self.tr("Row spacing (in Imperial; cm Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                30.0,
                False,
                5.0,
                120.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.TARGET_POPULATION,
                self.tr("Target population (seeds/acre Imperial; seeds/ha Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                32000.0,
                False,
                100.0,
                50000000.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MIN_POPULATION,
                self.tr("Minimum population (seeds/acre Imperial; seeds/ha Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                26000.0,
                False,
                0.0,
                50000000.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_POPULATION,
                self.tr("Maximum population (seeds/acre Imperial; seeds/ha Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                38000.0,
                False,
                1.0,
                50000000.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SEED_DEPTH,
                self.tr("Nominal seed depth (in Imperial; cm Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                2.0,
                False,
                0.1,
                25.4,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.NOMINAL_SPEED,
                self.tr("Nominal planting speed (mph Imperial; km/h Metric)"),
                QgsProcessingParameterNumber.Type.Double,
                5.0,
                False,
                0.1,
                30.0,
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
                self.PLANTING_MONTH_DAY,
                self.tr("Default planting date (MM-DD)"),
                "05-01",
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
                self.tr("Create planting polygon-grid surface"),
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
                self.SURFACE_ATTRIBUTES,
                self.tr("Surface attributes"),
                self.SURFACE_ATTRIBUTE_OPTIONS,
                allowMultiple=True,
                defaultValue=[0, 1, 2, 3],
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
        self.addOutput(QgsProcessingOutputString(self.CENTER_LAYER, "Planter-center layer"))
        self.addOutput(QgsProcessingOutputString(self.ROW_LAYER, "Row-unit layer"))
        self.addOutput(QgsProcessingOutputString(self.SURFACE_LAYER, "Planting surface"))
        self.addOutput(QgsProcessingOutputString(self.MANIFEST, "Run manifest"))

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
            transform = QgsCoordinateTransform(
                source_crs,
                QgsCoordinateReferenceSystem("EPSG:4326"),
                transform_context,
            )
            point = transform.transform(point)
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
            ("planting_id", QVariant.String),
            ("center_point_id", QVariant.String),
            ("record_type", QVariant.String),
            ("pass_id", QVariant.String),
            ("row_unit", QVariant.Int),
            ("section_on", QVariant.Bool),
            ("timestamp", QVariant.String),
            ("timezone", QVariant.String),
            ("heading", QVariant.Double),
            ("speed", QVariant.Double),
            ("speed_unit", QVariant.String),
            ("population", QVariant.Double),
            ("population_unit", QVariant.String),
            ("seed_spacing", QVariant.Double),
            ("seed_spacing_unit", QVariant.String),
            ("seed_depth", QVariant.Double),
            ("depth_unit", QVariant.String),
            ("singulation_pct", QVariant.Double),
            ("spacing_quality_pct", QVariant.Double),
            ("skips_pct", QVariant.Double),
            ("ride_quality_pct", QVariant.Double),
            ("ground_contact_pct", QVariant.Double),
            ("furrow_moisture_pct", QVariant.Double),
            ("furrow_temperature", QVariant.Double),
            ("temperature_unit", QVariant.String),
            ("uniform_furrow_pct", QVariant.Double),
            ("clean_furrow_pct", QVariant.Double),
            ("row_spacing", QVariant.Double),
            ("planter_width", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("is_headland", QVariant.Bool),
            ("variability_level", QVariant.String),
            ("variability_multiplier", QVariant.Double),
            ("latitude", QVariant.Double),
            ("longitude", QVariant.Double),
        ):
            fields.append(QgsField(name, variant))
        return fields

    @classmethod
    def _surface_fields(cls, attributes):
        fields = cls._common_fields()
        for name, variant in (
            ("cell_id", QVariant.String),
            ("grid_size", QVariant.Double),
            ("distance_unit", QVariant.String),
            ("surface_method", QVariant.String),
            ("source_points", QVariant.Int),
            ("heading", QVariant.Double),
            ("is_headland", QVariant.Bool),
            ("variability_level", QVariant.String),
            ("variability_multiplier", QVariant.Double),
            ("temperature_unit", QVariant.String),
        ):
            fields.append(QgsField(name, variant))
        for attribute in attributes:
            fields.append(QgsField(cls.SURFACE_FIELD_MAP[attribute], QVariant.Double))
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
    def _month_day(value):
        match = re.fullmatch(r"\s*(\d{1,2})-(\d{1,2})\s*", value or "")
        if not match:
            raise QgsProcessingException("Default planting date must use MM-DD")
        month, day = int(match.group(1)), int(match.group(2))
        try:
            datetime(2000, month, day)
        except ValueError as error:
            raise QgsProcessingException(f"Invalid default planting date: {error}") from error
        return month, day

    @staticmethod
    def _rectangle(x_min, y_min, x_max, y_max):
        return QgsGeometry.fromPolygonXY(
            [[
                QgsPointXY(x_min, y_min),
                QgsPointXY(x_max, y_min),
                QgsPointXY(x_max, y_max),
                QgsPointXY(x_min, y_max),
                QgsPointXY(x_min, y_min),
            ]]
        )

    @staticmethod
    def _automatic_bearing(geometry):
        _box, _area, angle, width, height = geometry.orientedMinimumBoundingBox()
        return (angle if width >= height else angle + 90.0) % 180.0

    @staticmethod
    def _pass_lines(geometry, bearing, swath_width):
        angle = math.radians(bearing)
        direction_x, direction_y = math.sin(angle), math.cos(angle)
        normal_x, normal_y = math.cos(angle), -math.sin(angle)
        bbox = geometry.boundingBox()
        corners = (
            (bbox.xMinimum(), bbox.yMinimum()),
            (bbox.xMinimum(), bbox.yMaximum()),
            (bbox.xMaximum(), bbox.yMinimum()),
            (bbox.xMaximum(), bbox.yMaximum()),
        )
        along = [x * direction_x + y * direction_y for x, y in corners]
        across = [x * normal_x + y * normal_y for x, y in corners]
        along_min, along_max = min(along), max(along)
        across_min, across_max = min(across), max(across)
        margin = max(swath_width, along_max - along_min) * 0.05 + swath_width
        offsets = []
        offset = across_min + swath_width / 2.0
        while offset <= across_max + 1e-9:
            offsets.append(offset)
            offset += swath_width
        if not offsets:
            offsets = [(across_min + across_max) / 2.0]
        lines = []
        for offset in offsets:
            start = QgsPointXY(
                direction_x * (along_min - margin) + normal_x * offset,
                direction_y * (along_min - margin) + normal_y * offset,
            )
            end = QgsPointXY(
                direction_x * (along_max + margin) + normal_x * offset,
                direction_y * (along_max + margin) + normal_y * offset,
            )
            clipped = QgsGeometry.fromPolylineXY([start, end]).intersection(geometry)
            if clipped.isEmpty() or QgsWkbTypes.geometryType(clipped.wkbType()) != QgsWkbTypes.GeometryType.LineGeometry:
                continue
            parts = clipped.asMultiPolyline() if clipped.isMultipart() else [clipped.asPolyline()]
            for part in parts:
                if len(part) >= 2:
                    line = QgsGeometry.fromPolylineXY(part)
                    if line.length() > 0.01:
                        lines.append(line)
        return lines

    @staticmethod
    def _headland_lines(geometry, headland_passes, swath_width):
        """Return machine-center rings that follow the complete field perimeter."""

        if headland_passes <= 0 or swath_width <= 0:
            return []
        offsets = [
            (pass_index + 0.5) * swath_width
            for pass_index in range(int(headland_passes))
        ]

        lines = []
        for offset in offsets:
            inset = geometry.buffer(-offset, 8)
            if inset.isEmpty():
                continue
            polygons = inset.asMultiPolygon() if inset.isMultipart() else [inset.asPolygon()]
            for polygon in polygons:
                for ring in polygon:
                    if len(ring) >= 2:
                        line = QgsGeometry.fromPolylineXY(ring)
                        if line.length() > 0.01:
                            lines.append(line)
        return lines

    @classmethod
    def _operation_passes(cls, geometry, bearing, swath_width, headland_passes):
        """Build straight interior passes plus full-perimeter headland rings."""

        headland_width = max(0, int(headland_passes)) * swath_width
        if headland_width > 0:
            interior = geometry.buffer(-headland_width, 8)
            main_lines = (
                cls._pass_lines(interior, bearing, swath_width)
                if not interior.isEmpty()
                else []
            )
            headland_lines = cls._headland_lines(
                geometry, headland_passes, swath_width
            )
        else:
            interior = geometry
            main_lines = cls._pass_lines(geometry, bearing, swath_width)
            headland_lines = []
        return (
            [(line, bearing, False) for line in main_lines]
            + [(line, None, True) for line in headland_lines],
            interior,
        )

    @staticmethod
    def _line_heading(line, distance_along):
        """Return the local clockwise-from-north heading along a curved pass."""

        length = line.length()
        delta = min(1.0, max(0.05, length * 0.001))
        before = line.interpolate(max(0.0, distance_along - delta)).asPoint()
        after = line.interpolate(min(length, distance_along + delta)).asPoint()
        return math.degrees(math.atan2(after.x() - before.x(), after.y() - before.y())) % 360.0

    @staticmethod
    def _line_points(line, spacing):
        length = line.length()
        count = max(1, int(math.ceil(length / max(0.01, spacing))))
        return [
            (length * (index + 0.5) / count, line.interpolate(length * (index + 0.5) / count).asPoint())
            for index in range(count)
        ]

    @staticmethod
    def _seed_spacing(population, row_spacing, units):
        return units.seed_spacing(population, row_spacing)

    @staticmethod
    def _spatial_effect(point, bbox, seed):
        width = max(1.0, bbox.width())
        height = max(1.0, bbox.height())
        normalized_x = (point.x() - bbox.xMinimum()) / width
        normalized_y = (point.y() - bbox.yMinimum()) / height
        phase_x = (seed % 1009) / 1009.0 * 2.0 * math.pi
        phase_y = (seed % 1013) / 1013.0 * 2.0 * math.pi
        return 0.5 * math.sin(2.0 * math.pi * normalized_x + phase_x) + 0.5 * math.cos(
            2.0 * math.pi * normalized_y + phase_y
        )

    @classmethod
    def _values(
        cls,
        point,
        bbox,
        point_seed,
        pass_number,
        target_population,
        minimum_population,
        maximum_population,
        nominal_speed,
        nominal_depth,
        row_spacing,
        multiplier,
        is_headland,
        units,
    ):
        # This seeded generator is part of reproducible fake data, not cryptography.
        rng = random.Random(point_seed)  # nosec B311
        spatial = cls._spatial_effect(point, bbox, point_seed)
        pass_effect = math.sin(pass_number * 1.618 + (point_seed % 97) / 97.0)
        population_factor = (
            1.0
            + spatial * 0.018 * multiplier
            + pass_effect * 0.006 * multiplier
            + rng.gauss(0.0, 0.004 * multiplier)
        )
        if is_headland:
            population_factor *= 0.975
        population = max(
            minimum_population,
            min(maximum_population, target_population * population_factor),
        )
        speed_factor = 1.0 + spatial * 0.025 * multiplier + rng.gauss(0.0, 0.008 * multiplier)
        if is_headland:
            speed_factor *= 0.88
        speed = max(nominal_speed * 0.4, min(nominal_speed * 1.3, nominal_speed * speed_factor))
        depth = nominal_depth + spatial * 0.04 * multiplier + rng.gauss(0.0, 0.05 * multiplier)
        minimum_depth = 0.25 if units.metric else 0.1
        maximum_depth = 25.4 if units.metric else 10.0
        depth = max(minimum_depth, min(maximum_depth, depth))
        quality_penalty = abs(spatial) * 1.1 * multiplier + abs(pass_effect) * 0.35
        headland_penalty = 1.4 if is_headland else 0.0
        singulation = max(
            88.0,
            min(100.0, 99.1 - quality_penalty - headland_penalty + rng.gauss(0.0, 0.25 * multiplier)),
        )
        skips = max(
            0.0,
            min(12.0, 100.0 - singulation + rng.gauss(0.25, 0.12 * multiplier)),
        )
        spacing_quality = max(
            75.0,
            min(100.0, singulation - skips * 0.75 - abs(spatial) * 0.8),
        )
        ride_quality = max(
            70.0,
            min(100.0, 97.0 - abs(speed_factor - 1.0) * 70.0 - headland_penalty),
        )
        ground_contact = max(
            75.0,
            min(100.0, 98.0 - abs(spatial) * 1.5 * multiplier - headland_penalty),
        )
        furrow_moisture = max(
            4.0,
            min(55.0, 22.0 + spatial * 5.0 * multiplier + rng.gauss(0.0, 1.0)),
        )
        furrow_temperature_f = max(
            35.0,
            min(100.0, 59.0 + spatial * 6.0 + rng.gauss(0.0, 1.2)),
        )
        furrow_temperature = (
            (furrow_temperature_f - 32.0) * 5.0 / 9.0
            if units.metric
            else furrow_temperature_f
        )
        uniform_furrow = max(
            70.0,
            min(100.0, 96.0 - abs(spatial) * 2.1 * multiplier - headland_penalty),
        )
        clean_furrow = max(
            70.0,
            min(100.0, 97.0 - abs(pass_effect) * 1.8 * multiplier - headland_penalty),
        )
        return {
            "population": population,
            "speed": speed,
            "seed_spacing": cls._seed_spacing(population, row_spacing, units),
            "seed_depth": depth,
            "singulation_pct": singulation,
            "spacing_quality_pct": spacing_quality,
            "skips_pct": skips,
            "ride_quality_pct": ride_quality,
            "ground_contact_pct": ground_contact,
            "furrow_moisture_pct": furrow_moisture,
            "furrow_temperature": furrow_temperature,
            "uniform_furrow_pct": uniform_furrow,
            "clean_furrow_pct": clean_furrow,
        }

    def _write_point_attributes(
        self,
        feature,
        run,
        child_seed,
        data_type,
        field_id,
        year,
        crop_name,
        planting_id,
        center_point_id,
        record_type,
        pass_id,
        row_unit,
        timestamp,
        heading,
        values,
        row_spacing,
        planter_width,
        is_headland,
        variability,
        multiplier,
        wgs84_point,
        point_field_names,
    ):
        attributes = self._common_values(
            run, child_seed, data_type, field_id, year, crop_name
        )
        attributes.update({
            "planting_id": planting_id,
            "center_point_id": center_point_id,
            "record_type": record_type,
            "pass_id": pass_id,
            "row_unit": row_unit,
            "section_on": True,
            "timestamp": timestamp,
            "timezone": run["timezone"],
            "heading": round(heading, 3),
            "speed": round(values["speed"], 3),
            "speed_unit": run["units"].speed_unit,
            "population": round(values["population"], 1),
            "population_unit": run["units"].population_unit,
            "seed_spacing": round(values["seed_spacing"], 3),
            "seed_spacing_unit": run["units"].small_distance_unit,
            "seed_depth": round(values["seed_depth"], 3),
            "depth_unit": run["units"].small_distance_unit,
            "singulation_pct": round(values["singulation_pct"], 3),
            "spacing_quality_pct": round(values["spacing_quality_pct"], 3),
            "skips_pct": round(values["skips_pct"], 3),
            "ride_quality_pct": round(values["ride_quality_pct"], 3),
            "ground_contact_pct": round(values["ground_contact_pct"], 3),
            "furrow_moisture_pct": round(values["furrow_moisture_pct"], 3),
            "furrow_temperature": round(values["furrow_temperature"], 3),
            "temperature_unit": "C" if run["units"].metric else "F",
            "uniform_furrow_pct": round(values["uniform_furrow_pct"], 3),
            "clean_furrow_pct": round(values["clean_furrow_pct"], 3),
            "row_spacing": row_spacing,
            "planter_width": planter_width,
            "distance_unit": run["units"].distance_unit,
            "is_headland": is_headland,
            "variability_level": variability,
            "variability_multiplier": multiplier,
            "latitude": round(wgs84_point.y(), 7),
            "longitude": round(wgs84_point.x(), 7),
        })
        feature.setAttributes([attributes.get(name) for name in point_field_names])

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
        year = self.parameterAsInt(parameters, self.CROP_YEAR, context)
        crop_name = self.parameterAsString(parameters, self.CROP_NAME, context).strip()
        if not crop_name:
            raise QgsProcessingException("Crop name is required")
        try:
            crop_provenance = crop_provenance_from_json(
                self.parameterAsString(parameters, self.CROP_PROVENANCE_JSON, context),
                crop_name,
                year,
            )
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise QgsProcessingException(str(error)) from error
        point_output = self.POINT_OUTPUT_OPTIONS[
            self.parameterAsEnum(parameters, self.POINT_OUTPUT, context)
        ]
        planter_width_ft = self.parameterAsDouble(parameters, self.PLANTER_WIDTH, context)
        row_units = self.parameterAsInt(parameters, self.ROW_UNITS, context)
        row_spacing_in = self.parameterAsDouble(parameters, self.ROW_SPACING, context)
        target_population = self.parameterAsDouble(parameters, self.TARGET_POPULATION, context)
        minimum_population = self.parameterAsDouble(parameters, self.MIN_POPULATION, context)
        maximum_population = self.parameterAsDouble(parameters, self.MAX_POPULATION, context)
        if not minimum_population <= target_population <= maximum_population:
            raise QgsProcessingException(
                "Population values must satisfy minimum <= target <= maximum"
            )
        expected_width_ft = (
            row_units * units.small_distance_to_meters(row_spacing_in)
            / units.distance_to_meters(1.0)
        )
        width_difference = abs(planter_width_ft - expected_width_ft) / max(0.01, expected_width_ft)
        if width_difference > 0.20:
            raise QgsProcessingException(
                f"Planter width ({planter_width_ft:g} {units.distance_unit}) differs by more than 20% from "
                f"{row_units} rows x {row_spacing_in:g} {units.small_distance_unit} "
                f"({expected_width_ft:g} {units.distance_unit})"
            )
        if width_difference > 0.05:
            feedback.pushWarning(
                "Planter width and row count x spacing differ by more than 5%; "
                "pass spacing will use planter width and row offsets will use row spacing"
            )
        nominal_depth = self.parameterAsDouble(parameters, self.SEED_DEPTH, context)
        nominal_speed = self.parameterAsDouble(parameters, self.NOMINAL_SPEED, context)
        logging_interval = self.parameterAsDouble(parameters, self.LOGGING_INTERVAL, context)
        headland_passes = self.parameterAsInt(parameters, self.HEADLAND_PASSES, context)
        direction_mode = self.DIRECTION_OPTIONS[
            self.parameterAsEnum(parameters, self.DIRECTION_MODE, context)
        ]
        manual_bearing = self.parameterAsDouble(parameters, self.MANUAL_BEARING, context)
        month, day = self._month_day(
            self.parameterAsString(parameters, self.PLANTING_MONTH_DAY, context)
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
        surface_grid_size_ft = self.parameterAsDouble(
            parameters, self.SURFACE_GRID_SIZE, context
        )
        surface_indexes = self.parameterAsEnums(parameters, self.SURFACE_ATTRIBUTES, context)
        surface_attributes = [
            self.SURFACE_ATTRIBUTE_OPTIONS[index] for index in surface_indexes
        ]
        if create_surface and not surface_attributes:
            raise QgsProcessingException("Select at least one planting surface attribute")
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
        working_crs = self._working_crs(source_crs, features, transform_context)
        to_working = QgsCoordinateTransform(source_crs, working_crs, transform_context)
        to_source = QgsCoordinateTransform(working_crs, source_crs, transform_context)
        to_wgs84 = QgsCoordinateTransform(
            working_crs, QgsCoordinateReferenceSystem("EPSG:4326"), transform_context
        )
        planter_width_m = units.distance_to_meters(planter_width_ft)
        row_spacing_m = units.small_distance_to_meters(row_spacing_in)
        headland_width_m = headland_passes * planter_width_m
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
        if total_area_acres > 5000.0 + 0.01:
            raise QgsProcessingException(
                f"Selected fields total {total_area_acres:,.1f} acres; the v1 limit is 5,000 acres"
            )
        estimated_center = max(
            1, int(math.ceil(total_area_m2 / max(0.01, planter_width_m * point_spacing_m)))
        )
        estimated_rows = estimated_center * row_units if point_output in {"Row Units", "Both"} else 0
        estimated_surface = (
            int(math.ceil(total_area_m2 / max(0.01, surface_grid_size_m**2)))
            if create_surface
            else 0
        )
        feedback.pushInfo(
            f"Preflight estimate: {estimated_center:,} planter-center positions, "
            f"up to {estimated_rows:,} row-unit points, and approximately "
            f"{estimated_surface:,} surface cells"
        )
        if estimated_center + estimated_rows + estimated_surface >= 100_000:
            feedback.pushWarning(
                "This run may take a while. QGIS must remain open until processing finishes."
            )

        created_at = datetime.now().astimezone().isoformat(timespec="seconds")
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        run_folder = parent_output / f"Fake_Farm_Data_{run_id}"
        run_folder.mkdir(parents=False, exist_ok=False)
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
            "units": units,
            "field_identities": {
                feature_field_id(feature, index): feature_field_identity(feature, index)
                for index, feature in enumerate(features, start=1)
            },
        }

        create_center_output = point_output in {"Planter Center", "Both"}
        create_row_output = point_output in {"Row Units", "Both"}
        point_fields = self._point_fields()
        point_field_names = point_fields.names()
        center_path = year_folder / f"fake_planting_center_{year}.gpkg"
        row_path = year_folder / f"fake_planting_rows_{year}.gpkg"
        surface_path = year_folder / f"fake_planting_surface_{year}.gpkg"
        center_writer = (
            self._writer(
                center_path,
                point_fields,
                source_crs,
                QgsWkbTypes.Type.Point,
                f"fake_planting_center_{year}",
            )
            if create_center_output
            else None
        )
        row_writer = (
            self._writer(
                row_path,
                point_fields,
                source_crs,
                QgsWkbTypes.Type.Point,
                f"fake_planting_rows_{year}",
            )
            if create_row_output
            else None
        )
        surface_fields = self._surface_fields(surface_attributes) if create_surface else None
        surface_writer = (
            self._writer(
                surface_path,
                surface_fields,
                source_crs,
                QgsWkbTypes.Type.MultiPolygon,
                f"fake_planting_surface_{year}",
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
            "planting": {
                "crop_name": crop_name,
                "crop_provenance": crop_provenance,
                "point_output": point_output,
                "planter_width_feet": planter_width_ft,
                "row_units": row_units,
                "row_spacing_inches": row_spacing_in,
                "target_population_seeds_per_acre": target_population,
                "population_minimum": minimum_population,
                "population_maximum": maximum_population,
                "nominal_seed_depth_inches": nominal_depth,
                "nominal_speed_mph": nominal_speed,
                "logging_interval_seconds": logging_interval,
                "headland_passes": headland_passes,
                "headland_width": round(
                    headland_width_m / units.distance_to_meters(1.0), 3
                ),
                "direction_mode": direction_mode,
                "manual_bearing": manual_bearing if direction_mode == "Manual" else None,
                "variability_level": variability,
                "variability_multiplier": multiplier,
                "surface_created": create_surface,
                "surface_grid_size_feet": surface_grid_size_ft,
                "surface_attributes": surface_attributes,
                "distance_unit": units.distance_unit,
                "small_distance_unit": units.small_distance_unit,
                "speed_unit": units.speed_unit,
                "population_unit": units.population_unit,
            },
            "field_bearings": {},
            "outputs": [],
            "estimates": {
                "planter_center_positions": estimated_center,
                "row_unit_points": estimated_rows,
                "planting_surface_cells": estimated_surface,
            },
            "counts": {
                "planter_center_points": 0,
                "row_unit_points": 0,
                "inactive_row_positions_skipped": 0,
                "planting_surface_cells": 0,
            },
        }
        manifest_path = run_folder / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        try:
            progress = ProgressReporter(feedback, len(features), "Planting")
            date_seed = stable_seed(master_seed, "planting", year, "date")
            planting_date = deterministic_operation_date(
                year, month, day, date_window, date_seed
            )
            operation_start = datetime.combine(planting_date, time(8, 0, 0))
            center_counter = 1
            row_counter = 1
            surface_counter = 1
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
                child_seed = stable_seed(master_seed, field_id, year, "planting")
                bearing = (
                    self._automatic_bearing(geometry)
                    if direction_mode == "Automatic"
                    else manual_bearing
                )
                manifest["field_bearings"][field_id] = round(bearing, 3)
                pass_specs, headland_interior = self._operation_passes(
                    geometry, bearing, planter_width_m, headland_passes
                )
                feedback.pushInfo(
                    f"{field_id} {year}: creating {len(pass_specs)} planting pass segments "
                    f"at {bearing:.1f} degrees"
                )
                bbox = geometry.boundingBox()
                field_samples = []
                elapsed_seconds = 0.0
                for pass_index, (original_line, pass_bearing, is_headland_pass) in enumerate(
                    pass_specs, start=1
                ):
                    if feedback.isCanceled():
                        manifest["status"] = "incomplete"
                        break
                    reverse = pass_index % 2 == 0
                    if reverse:
                        points = original_line.asPolyline()
                        line = QgsGeometry.fromPolylineXY(list(reversed(points)))
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
                    pass_id = f"P{field_index:03d}_{pass_index:04d}"
                    for position_index, (distance_along, point) in enumerate(
                        self._line_points(line, point_spacing_m), start=1
                    ):
                        heading = (
                            pass_heading
                            if pass_heading is not None
                            else self._line_heading(line, distance_along)
                        )
                        is_headland = is_headland_pass
                        point_seed = stable_seed(
                            child_seed, "center", pass_index, position_index
                        )
                        values = self._values(
                            point,
                            bbox,
                            point_seed,
                            pass_index,
                            target_population,
                            minimum_population,
                            maximum_population,
                            nominal_speed,
                            nominal_depth,
                            row_spacing_in,
                            multiplier,
                            is_headland,
                            units,
                        )
                        timestamp = (
                            operation_start
                            + timedelta(
                                seconds=elapsed_seconds
                                + distance_along / max(0.01, nominal_speed_mps)
                            )
                        ).isoformat(timespec="seconds")
                        center_id = f"PC{year}_{field_index:03d}_{center_counter:07d}"
                        point_source = to_source.transform(QgsPointXY(point))
                        point_wgs84 = to_wgs84.transform(QgsPointXY(point))
                        if center_writer is not None:
                            feature = QgsFeature(point_fields)
                            feature.setGeometry(QgsGeometry.fromPointXY(point_source))
                            self._write_point_attributes(
                                feature,
                                run,
                                child_seed,
                                "planting_center",
                                field_id,
                                year,
                                crop_name,
                                center_id,
                                center_id,
                                "planter_center",
                                pass_id,
                                0,
                                timestamp,
                                heading,
                                values,
                                row_spacing_in,
                                planter_width_ft,
                                is_headland,
                                variability,
                                multiplier,
                                point_wgs84,
                                point_field_names,
                            )
                            if not center_writer.addFeature(feature):
                                raise QgsProcessingException(
                                    f"Could not write planter-center point for {field_id}"
                                )
                            manifest["counts"]["planter_center_points"] += 1
                        field_samples.append((QgsPointXY(point), values, is_headland))

                        if row_writer is not None:
                            heading_radians = math.radians(heading)
                            normal_x = math.cos(heading_radians)
                            normal_y = -math.sin(heading_radians)
                            for row_number in range(1, row_units + 1):
                                offset = (row_number - (row_units + 1) / 2.0) * row_spacing_m
                                row_point = QgsPointXY(
                                    point.x() + normal_x * offset,
                                    point.y() + normal_y * offset,
                                )
                                row_geometry = QgsGeometry.fromPointXY(row_point)
                                if not geometry.intersects(row_geometry):
                                    manifest["counts"]["inactive_row_positions_skipped"] += 1
                                    continue
                                row_seed = stable_seed(point_seed, "row", row_number)
                                # Reproducible fake row variation; not cryptography.
                                row_rng = random.Random(row_seed)  # nosec B311
                                row_values = dict(values)
                                row_values["population"] = max(
                                    minimum_population,
                                    min(
                                        maximum_population,
                                        values["population"]
                                        * (1.0 + row_rng.gauss(0.0, 0.004 * multiplier)),
                                    ),
                                )
                                row_values["seed_spacing"] = self._seed_spacing(
                                    row_values["population"], row_spacing_in, units
                                )
                                minimum_depth = 0.25 if units.metric else 0.1
                                maximum_depth = 25.4 if units.metric else 10.0
                                row_values["seed_depth"] = max(
                                    minimum_depth,
                                    min(
                                        maximum_depth,
                                        values["seed_depth"]
                                        + row_rng.gauss(0.0, 0.025 * multiplier),
                                    ),
                                )
                                row_source = to_source.transform(row_point)
                                row_wgs84 = to_wgs84.transform(row_point)
                                row_id = f"PR{year}_{field_index:03d}_{row_counter:09d}"
                                row_feature = QgsFeature(point_fields)
                                row_feature.setGeometry(QgsGeometry.fromPointXY(row_source))
                                self._write_point_attributes(
                                    row_feature,
                                    run,
                                    child_seed,
                                    "planting_row_unit",
                                    field_id,
                                    year,
                                    crop_name,
                                    row_id,
                                    center_id,
                                    "row_unit",
                                    pass_id,
                                    row_number,
                                    timestamp,
                                    heading,
                                    row_values,
                                    row_spacing_in,
                                    planter_width_ft,
                                    is_headland,
                                    variability,
                                    multiplier,
                                    row_wgs84,
                                    point_field_names,
                                )
                                if not row_writer.addFeature(row_feature):
                                    raise QgsProcessingException(
                                        f"Could not write row-unit point for {field_id}"
                                    )
                                row_counter += 1
                                manifest["counts"]["row_unit_points"] += 1
                        center_counter += 1
                    elapsed_seconds += line.length() / max(0.01, nominal_speed_mps) + 30.0

                if surface_writer is not None and field_samples:
                    buckets = {}
                    for sample_point, sample_values, sample_headland in field_samples:
                        column = int(
                            math.floor((sample_point.x() - bbox.xMinimum()) / surface_grid_size_m)
                        )
                        row = int(
                            math.floor((sample_point.y() - bbox.yMinimum()) / surface_grid_size_m)
                        )
                        buckets.setdefault((column, row), []).append(
                            (sample_point, sample_values, sample_headland)
                        )
                    row_index = 0
                    y = bbox.yMinimum()
                    while y < bbox.yMaximum():
                        column_index = 0
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
                                candidates = buckets.get((column_index, row_index), [])
                                samples = [
                                    item
                                    for item in candidates
                                    if clipped.intersects(QgsGeometry.fromPointXY(item[0]))
                                ]
                                centroid = clipped.centroid().asPoint()
                                cell_headland = (
                                    headland_width_m > 0
                                    and (
                                        headland_interior.isEmpty()
                                        or not headland_interior.intersects(
                                            QgsGeometry.fromPointXY(QgsPointXY(centroid))
                                        )
                                    )
                                )
                                if samples:
                                    cell_values = {
                                        key: sum(item[1][key] for item in samples) / len(samples)
                                        for key in self.SURFACE_FIELD_MAP.values()
                                    }
                                    surface_method = "point_mean"
                                else:
                                    cell_seed = stable_seed(
                                        child_seed, "surface", row_index, column_index
                                    )
                                    cell_values = self._values(
                                        centroid,
                                        bbox,
                                        cell_seed,
                                        0,
                                        target_population,
                                        minimum_population,
                                        maximum_population,
                                        nominal_speed,
                                        nominal_depth,
                                        row_spacing_in,
                                        multiplier,
                                        cell_headland,
                                        units,
                                    )
                                    surface_method = "generated_centroid"
                                clipped.transform(to_source)
                                if not clipped.isMultipart():
                                    clipped.convertToMultiType()
                                surface_feature = QgsFeature(surface_fields)
                                surface_feature.setGeometry(clipped)
                                self._set_common(
                                    surface_feature,
                                    run,
                                    child_seed,
                                    "planting_surface",
                                    field_id,
                                    year,
                                    crop_name,
                                )
                                for name, value in {
                                    "cell_id": f"PSC{year}_{field_index:03d}_{surface_counter:07d}",
                                    "grid_size": surface_grid_size_ft,
                                    "distance_unit": units.distance_unit,
                                    "surface_method": surface_method,
                                    "source_points": len(samples),
                                    "heading": round(bearing, 3),
                                    "is_headland": cell_headland,
                                    "variability_level": variability,
                                    "variability_multiplier": multiplier,
                                    "temperature_unit": "C" if units.metric else "F",
                                }.items():
                                    surface_feature.setAttribute(name, value)
                                for attribute in surface_attributes:
                                    field_name = self.SURFACE_FIELD_MAP[attribute]
                                    digits = 1 if field_name == "population" else 3
                                    surface_feature.setAttribute(
                                        field_name, round(cell_values[field_name], digits)
                                    )
                                if not surface_writer.addFeature(surface_feature):
                                    raise QgsProcessingException(
                                        f"Could not write planting surface cell for {field_id}"
                                    )
                                surface_counter += 1
                                manifest["counts"]["planting_surface_cells"] += 1
                            x += surface_grid_size_m
                            column_index += 1
                        y += surface_grid_size_m
                        row_index += 1
                progress.update(
                    field_index,
                    f"{field_id} {year}",
                    manifest["counts"]["planter_center_points"]
                    + manifest["counts"]["row_unit_points"]
                    + manifest["counts"]["planting_surface_cells"],
                    force=True,
                )

            del center_writer
            del row_writer
            del surface_writer
            if create_center_output:
                manifest["outputs"].append(str(center_path.relative_to(run_folder)))
            if create_row_output:
                manifest["outputs"].append(str(row_path.relative_to(run_folder)))
            if create_surface:
                manifest["outputs"].append(str(surface_path.relative_to(run_folder)))
            if manifest["status"] == "running":
                write_gpkg_run_metadata(
                    [
                        path
                        for path, enabled_output in (
                            (center_path, create_center_output),
                            (row_path, create_row_output),
                            (surface_path, create_surface),
                        )
                        if enabled_output
                    ],
                    manifest,
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
            f"Created {manifest['counts']['planter_center_points']:,} planter-center points, "
            f"{manifest['counts']['row_unit_points']:,} row-unit points, and "
            f"{manifest['counts']['planting_surface_cells']:,} surface cells"
        )
        return {
            self.OUTPUT_FOLDER: str(run_folder),
            self.CENTER_LAYER: str(center_path) if create_center_output else "",
            self.ROW_LAYER: str(row_path) if create_row_output else "",
            self.SURFACE_LAYER: str(surface_path) if create_surface else "",
            self.MANIFEST: str(manifest_path),
        }
