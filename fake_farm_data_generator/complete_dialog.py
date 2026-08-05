# SPDX-License-Identifier: GPL-3.0-or-later
"""Tabbed complete-run dialog backed by the Processing orchestrator."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import available_timezones

from qgis.PyQt.QtCore import (
    QDate,
    QProcess,
    QStandardPaths,
    QTimer,
    Qt,
    QUrl,
    QVariant,
)
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qgis.core import (
    QgsApplication,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProcessingFeedback,
    QgsProcessingUtils,
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsWkbTypes,
)

from .algorithms.complete_dataset import CreateCompleteFakeFarmDatasetAlgorithm
from .algorithms.yield_data import CreateFakeYieldAlgorithm
from .core.application_operations import (
    DIRECTION_MODES,
    OPERATION_TYPES,
    RATE_MODES,
    VARIABILITY_LEVELS,
    default_application_operation,
    normalize_application_operations,
)
from .core.generation import (
    FAKE_WARNING,
    feature_field_identity,
    normalize_timezone_label,
    parse_years,
)
from .core.point_estimator import estimate_complete_records
from .core.preflight_review import build_preflight_review_text, runtime_estimate_text
from .core.progress import format_duration
from .core.review_settings import (
    DEFAULT_REVIEW_MAX_FEATURES,
    MAX_REVIEW_MAX_FEATURES,
    MIN_REVIEW_MAX_FEATURES,
    normalize_review_max_features,
)
from .core.complete_settings import (
    DIRECTION_MODES as COMPLETE_DIRECTION_MODES,
    INTERPOLATION_METHODS,
    KRIGING_MODELS,
    LEVELS,
    PLANTING_POINT_OUTPUTS,
    PLANTING_SURFACE_ATTRIBUTES,
    SOIL_PLACEMENTS,
    default_planting_settings,
    default_soil_settings,
    default_yield_settings,
    normalize_planting_settings,
    normalize_soil_settings,
    normalize_yield_settings,
    planting_crop_profiles,
    resolve_soil_schedule,
)
from .core.units import metric_yield_profile
from .exporters import OUTPUT_FORMAT_OPTIONS
from .crops.manager import (
    parse_overrides,
    suggest_api_field_year_assignments,
)
from .crops.resolver import CropAssignment


def _qt_enum(name, scoped_enum):
    value = getattr(Qt, name, None)
    if value is not None:
        return value
    return getattr(getattr(Qt, scoped_enum), name)


def _class_enum(owner, name, scoped_enum):
    value = getattr(owner, name, None)
    if value is not None:
        return value
    return getattr(getattr(owner, scoped_enum), name)


QT_ITEM_IS_EDITABLE = _qt_enum("ItemIsEditable", "ItemFlag")
QT_ITEM_IS_USER_CHECKABLE = _qt_enum("ItemIsUserCheckable", "ItemFlag")
QT_WAIT_CURSOR = _qt_enum("WaitCursor", "CursorShape")
QT_WINDOW_MODAL = _qt_enum("WindowModal", "WindowModality")
QT_USER_ROLE = _qt_enum("UserRole", "ItemDataRole")
QT_CHECKED = _qt_enum("Checked", "CheckState")
QT_UNCHECKED = _qt_enum("Unchecked", "CheckState")
BUTTON_CLOSE = _class_enum(QDialogButtonBox, "Close", "StandardButton")
BUTTON_ACCEPT_ROLE = _class_enum(QDialogButtonBox, "AcceptRole", "ButtonRole")
MESSAGE_YES = _class_enum(QMessageBox, "Yes", "StandardButton")
MESSAGE_NO = _class_enum(QMessageBox, "No", "StandardButton")
MESSAGE_ACTION_ROLE = _class_enum(QMessageBox, "ActionRole", "ButtonRole")
MESSAGE_REJECT_ROLE = _class_enum(QMessageBox, "RejectRole", "ButtonRole")
PROCESS_MERGED_CHANNELS = _class_enum(QProcess, "MergedChannels", "ProcessChannelMode")
PROCESS_NOT_RUNNING = _class_enum(QProcess, "NotRunning", "ProcessState")
PROCESS_NORMAL_EXIT = _class_enum(QProcess, "NormalExit", "ExitStatus")


class CompleteDatasetDialog(QDialog):
    """Collect the complete-run parameters in the v1 tab structure."""

    APPLICATION_COLUMNS = [
        ("enabled", "Enabled"),
        ("year", "Year / All"),
        ("operation_id", "Operation ID"),
        ("operation_type", "Operation type"),
        ("product_name", "Product"),
        ("rate_mode", "Rate mode"),
        ("target_rate", "Target"),
        ("min_rate", "Minimum"),
        ("max_rate", "Maximum"),
        ("rate_unit", "Rate unit"),
        ("base_date", "Base date"),
        ("date_window", "+/- days"),
        ("equipment_width", "Width"),
        ("nominal_speed", "Speed"),
        ("logging_interval", "Log seconds"),
        ("headland_passes", "Headland passes"),
        ("direction_mode", "Direction"),
        ("manual_bearing", "Bearing"),
        ("variability_level", "Variability"),
        ("create_surface", "Surface"),
        ("surface_grid_size", "Grid size"),
    ]

    def __init__(self, iface, parent=None):
        super().__init__(parent or (iface.mainWindow() if iface else None))
        self.iface = iface
        self.output_folder = None
        self._preset_crop_overrides = {}
        self._generation_running = False
        self._generation_process = None
        self._generation_progress = None
        self._generation_error = ""
        self._generation_messages = []
        self._generation_output = ""
        self._generation_output_parent = None
        self._generation_existing_folders = set()
        self._generation_input_path = None
        self._generation_canceled = False
        self._generation_started_at = None
        self._generation_last_progress_marker = -1
        self._pending_runtime_estimate = ""
        self.create_soil = QCheckBox("Soil tests")
        self.create_planting = QCheckBox("Planting")
        self.create_applications = QCheckBox("As-applied")
        self.create_yield = QCheckBox("Yield")
        for checkbox in (
            self.create_soil,
            self.create_planting,
            self.create_applications,
            self.create_yield,
        ):
            checkbox.setChecked(False)
        self.setWindowTitle("Create Complete Fake Farm Dataset")
        self.resize(940, 720)
        root = QVBoxLayout(self)
        warning = QLabel(
            "FAKE DATA — FOR TESTING AND DEMONSTRATION ONLY — NOT FOR AGRONOMIC DECISIONS"
        )
        warning.setStyleSheet(
            "background:#9d1111;color:white;font-weight:700;padding:8px;border-radius:4px"
        )
        warning.setWordWrap(True)
        root.addWidget(warning)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_general()
        self._build_crops()
        self._build_soil()
        self._build_planting()
        self._build_applications()
        self._build_yield()
        self._build_outputs()
        for checkbox in (
            self.create_soil,
            self.create_planting,
            self.create_applications,
            self.create_yield,
        ):
            checkbox.toggled.connect(self._invalidate_review)
        self._application_unit_index = self.unit_system.currentIndex()
        self._unit_index = self.unit_system.currentIndex()
        self._yield_profile_unit_index = self.unit_system.currentIndex()
        self.unit_system.currentIndexChanged.connect(self._convert_unit_system)
        self.button_box = QDialogButtonBox(BUTTON_CLOSE)
        self.close_button = self.button_box.button(BUTTON_CLOSE)
        self.run_button = self.button_box.addButton("Review Run", BUTTON_ACCEPT_ROLE)
        self.run_button.clicked.connect(self.review_generation)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

    def _invalidate_review(self, *_args):
        self.execute_button.setEnabled(False)

    def setParameters(self, parameters):
        """Apply Processing API presets without exposing transport JSON to users."""

        if not isinstance(parameters, dict) or not parameters:
            return
        algorithm = CreateCompleteFakeFarmDatasetAlgorithm
        input_value = parameters.get(algorithm.INPUT)
        if input_value is not None:
            layer = input_value if hasattr(input_value, "fields") else None
            if layer is None:
                text = str(input_value)
                for candidate in QgsProject.instance().mapLayers().values():
                    if text in {candidate.id(), candidate.name(), candidate.source()}:
                        layer = candidate
                        break
            if layer is not None:
                self._refresh_boundary_layers()
                self._set_boundary_layers([layer])

        for name, combo in (
            (algorithm.FIELD_ID_FIELD, self.field_id_field),
            (algorithm.FIELD_NAME_FIELD, self.field_name_field),
            (algorithm.FARM_NAME_FIELD, self.farm_name_field),
            (algorithm.GROWER_NAME_FIELD, self.grower_name_field),
        ):
            if name in parameters:
                self._set_mapping_field(combo, parameters.get(name, ""))

        if algorithm.UNIT_SYSTEM in parameters:
            value = parameters[algorithm.UNIT_SYSTEM]
            if isinstance(value, str) and not value.strip().isdigit():
                self._set_combo_text(self.unit_system, value, "unit system")
            else:
                self.unit_system.setCurrentIndex(int(value))
        if algorithm.YEARS in parameters:
            self._set_years(parameters[algorithm.YEARS])
        if algorithm.TIMEZONE in parameters:
            self._set_timezone(parameters[algorithm.TIMEZONE])
        if algorithm.RANDOM_SEED in parameters:
            self.seed.setValue(int(parameters[algorithm.RANDOM_SEED]))
        if algorithm.OUTPUT_DIR in parameters:
            self.output_directory.setText(str(parameters[algorithm.OUTPUT_DIR] or ""))

        for name, checkbox in (
            (algorithm.CREATE_SOIL, self.create_soil),
            (algorithm.CREATE_PLANTING, self.create_planting),
            (algorithm.CREATE_APPLICATIONS, self.create_applications),
            (algorithm.CREATE_YIELD, self.create_yield),
        ):
            if name in parameters:
                checkbox.setChecked(bool(parameters[name]))
        if algorithm.SOIL_INTERVAL in parameters:
            self.soil_interval.setValue(int(parameters[algorithm.SOIL_INTERVAL]))
        if algorithm.SOIL_FIRST_YEAR in parameters:
            value = str(parameters[algorithm.SOIL_FIRST_YEAR] or "")
            index = self.soil_first_year.findData(value)
            self.soil_first_year.setCurrentIndex(index if index >= 0 else 0)
        if algorithm.SOIL_FINAL_YEAR in parameters:
            value = str(parameters[algorithm.SOIL_FINAL_YEAR] or "")
            index = self.soil_final_year.findData(value)
            self.soil_final_year.setCurrentIndex(index if index >= 0 else 0)

        for name, normalizer, apply in (
            (algorithm.SOIL_SETTINGS_JSON, normalize_soil_settings, self._apply_soil_settings),
            (
                algorithm.PLANTING_SETTINGS_JSON,
                normalize_planting_settings,
                self._apply_planting_settings,
            ),
            (algorithm.YIELD_SETTINGS_JSON, normalize_yield_settings, self._apply_yield_settings),
        ):
            raw = parameters.get(name)
            if raw not in (None, ""):
                apply(normalizer(raw, self.unit_system.currentIndex()))

        raw_operations = parameters.get(algorithm.APPLICATION_OPERATIONS_JSON)
        if raw_operations not in (None, ""):
            raw_text = (
                json.dumps(raw_operations)
                if isinstance(raw_operations, list)
                else str(raw_operations)
            )
            operations = normalize_application_operations(
                raw_text, parse_years(self._years_text())
            )
            self._load_application_rows(operations)

        for name, combo in (
            (algorithm.CROP_LOOKUP_MODE, self.crop_mode),
            (algorithm.CROP_PROFILE, self.manual_crop),
        ):
            if name in parameters:
                value = parameters[name]
                if isinstance(value, str) and not value.strip().isdigit():
                    self._set_combo_text(combo, value, name)
                else:
                    combo.setCurrentIndex(int(value))
        if algorithm.LOCAL_CDL_PATH in parameters:
            self.local_cdl.setText(str(parameters[algorithm.LOCAL_CDL_PATH] or ""))
        if algorithm.CDL_CACHE_DIRECTORY in parameters:
            self.cdl_cache.setText(
                str(parameters[algorithm.CDL_CACHE_DIRECTORY] or "")
            )
        raw_overrides = parameters.get(algorithm.CROP_OVERRIDES_JSON)
        if raw_overrides not in (None, ""):
            self._preset_crop_overrides = parse_overrides(
                str(raw_overrides), CreateFakeYieldAlgorithm.CROP_OPTIONS
            )

        selected_formats = parameters.get(algorithm.OUTPUT_FORMATS)
        if selected_formats is not None:
            if not isinstance(selected_formats, (list, tuple)):
                selected_formats = [selected_formats]
            selected_indexes = set()
            for value in selected_formats:
                if isinstance(value, str) and not value.strip().isdigit():
                    if value in OUTPUT_FORMAT_OPTIONS:
                        selected_indexes.add(OUTPUT_FORMAT_OPTIONS.index(value))
                else:
                    selected_indexes.add(int(value))
            for index, checkbox in enumerate(self.format_checks):
                checkbox.setChecked(index == 0 or index in selected_indexes)
        if algorithm.REVIEW_MAX_FEATURES in parameters:
            self.review_max_features.setValue(
                normalize_review_max_features(parameters[algorithm.REVIEW_MAX_FEATURES])
            )

    @staticmethod
    def _tab():
        widget = QWidget()
        widget.setLayout(QFormLayout())
        return widget

    @staticmethod
    def _scroll_form():
        content = QWidget()
        form = QFormLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        return scroll, form

    @staticmethod
    def _double(value, minimum, maximum, decimals=3):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        control.setSingleStep(0.1)
        return control

    @staticmethod
    def _is_polygon_layer(layer):
        return (
            layer is not None
            and hasattr(layer, "wkbType")
            and QgsWkbTypes.geometryType(layer.wkbType())
            == QgsWkbTypes.PolygonGeometry
        )

    def _refresh_boundary_layers(self):
        checked = {
            self.boundary_layers.item(index).data(QT_USER_ROLE)
            for index in range(self.boundary_layers.count())
            if self.boundary_layers.item(index).checkState() == QT_CHECKED
        }
        if not checked and self.iface is not None:
            active = self.iface.activeLayer()
            if self._is_polygon_layer(active):
                checked.add(active.id())
        layers = sorted(
            (
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if self._is_polygon_layer(layer)
            ),
            key=lambda layer: layer.name().casefold(),
        )
        self.boundary_layers.blockSignals(True)
        self.boundary_layers.clear()
        for layer in layers:
            item = QListWidgetItem(layer.name())
            item.setData(QT_USER_ROLE, layer.id())
            item.setFlags(item.flags() | QT_ITEM_IS_USER_CHECKABLE)
            item.setCheckState(QT_CHECKED if layer.id() in checked else QT_UNCHECKED)
            self.boundary_layers.addItem(item)
        if layers and not checked:
            self.boundary_layers.item(0).setCheckState(QT_CHECKED)
        self.boundary_layers.blockSignals(False)
        self._boundary_selection_changed()

    def _selected_boundary_layers(self):
        layers = []
        project = QgsProject.instance()
        for index in range(self.boundary_layers.count()):
            item = self.boundary_layers.item(index)
            if item.checkState() != QT_CHECKED:
                continue
            layer = project.mapLayer(str(item.data(QT_USER_ROLE)))
            if self._is_polygon_layer(layer):
                layers.append(layer)
        return layers

    def _set_boundary_layers(self, layers):
        requested = {layer.id() for layer in layers if self._is_polygon_layer(layer)}
        for index in range(self.boundary_layers.count()):
            item = self.boundary_layers.item(index)
            item.setCheckState(
                QT_CHECKED if item.data(QT_USER_ROLE) in requested else QT_UNCHECKED
            )

    def _boundary_selection_changed(self, *_args):
        self._update_field_mapping_choices(None)
        self._crop_review_signature_value = None

    def _combined_boundary_layer(self):
        layers = self._selected_boundary_layers()
        if not layers:
            raise ValueError("Select at least one field-boundary layer")
        target_crs = layers[0].crs()
        if not target_crs.isValid():
            raise ValueError(f"Boundary layer {layers[0].name()} has an invalid CRS")
        layer = QgsVectorLayer(
            f"MultiPolygon?crs={target_crs.authid()}",
            "Selected field boundaries",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("field_id", QVariant.String),
                QgsField("field_name", QVariant.String),
                QgsField("farm_name", QVariant.String),
                QgsField("grower_name", QVariant.String),
                QgsField("source_layer", QVariant.String),
            ]
        )
        layer.updateFields()
        output = []
        used_ids = set()
        field_index = 0
        mapping = self._field_mapping()
        transform_context = QgsProject.instance().transformContext()
        for source in layers:
            if not source.crs().isValid():
                raise ValueError(f"Boundary layer {source.name()} has an invalid CRS")
            source_fields = set(source.fields().names())
            source_mapping = {
                name: value if value in source_fields else ""
                for name, value in mapping.items()
            }
            transform = (
                QgsCoordinateTransform(source.crs(), target_crs, transform_context)
                if source.crs() != target_crs
                else None
            )
            for feature in self._selected_features(source):
                if not feature.hasGeometry() or feature.geometry().isEmpty():
                    continue
                field_index += 1
                identity = feature_field_identity(feature, field_index, source_mapping)
                base_id = identity["field_id"]
                unique_id = base_id
                suffix = 2
                while unique_id in used_ids:
                    unique_id = f"{base_id}_{suffix}"
                    suffix += 1
                used_ids.add(unique_id)
                identity["field_id"] = unique_id
                if not identity["field_name"]:
                    identity["field_name"] = unique_id
                geometry = QgsGeometry(feature.geometry())
                if transform is not None:
                    geometry.transform(transform)
                if not QgsWkbTypes.isMultiType(geometry.wkbType()):
                    geometry.convertToMultiType()
                result = QgsFeature(layer.fields())
                result.setGeometry(geometry)
                for name, value in {
                    **identity,
                    "source_layer": source.name(),
                }.items():
                    result.setAttribute(name, value)
                output.append(result)
        if not output:
            raise ValueError("The selected boundary layers contain no usable polygons")
        if len(output) > 20:
            raise ValueError(f"Selected {len(output)} fields; the limit is 20")
        provider.addFeatures(output)
        layer.updateExtents()
        return layer

    def _sync_year_text_from_buttons(self, *_args):
        years = sorted(year for year, button in self.year_buttons.items() if button.isChecked())
        text = ",".join(str(year) for year in years)
        if self.years.text() != text:
            self.years.blockSignals(True)
            self.years.setText(text)
            self.years.blockSignals(False)
        self._refresh_soil_year_choices()
        self._crop_review_signature_value = None

    def _sync_year_buttons_from_text(self, text):
        try:
            selected = set(parse_years(text))
        except ValueError:
            return
        for year, button in self.year_buttons.items():
            button.blockSignals(True)
            button.setChecked(year in selected)
            button.blockSignals(False)
        self._refresh_soil_year_choices()
        self._crop_review_signature_value = None

    def _years_text(self):
        return self.years.text().strip()

    def _set_years(self, value):
        years = parse_years(value)
        unavailable = sorted(set(years) - set(self.year_buttons))
        if unavailable:
            raise ValueError(
                "The complete dialog offers the current year and previous nine years; "
                f"unavailable selection: {', '.join(map(str, unavailable))}"
            )
        self.years.setText(",".join(str(year) for year in years))

    def _set_all_data_types(self, checked):
        for checkbox in (
            self.create_soil,
            self.create_planting,
            self.create_applications,
            self.create_yield,
        ):
            checkbox.setChecked(bool(checked))
        self.execute_button.setEnabled(False)

    def _timezone_text(self):
        return str(self.timezone.currentData() or "")

    def _set_timezone(self, value):
        text = str(value or "").strip()
        index = self.timezone.findData(text)
        if index < 0:
            raise ValueError(f"Unsupported timezone: {text}")
        self.timezone.setCurrentIndex(index)

    def _refresh_soil_year_choices(self):
        if not hasattr(self, "soil_first_year"):
            return
        try:
            years = parse_years(self.years.text())
        except ValueError:
            years = []
        for combo in (self.soil_first_year, self.soil_final_year):
            previous = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Automatic", "")
            for year in years:
                combo.addItem(str(year), str(year))
            index = combo.findData(previous)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

    def _build_general(self):
        tab = self._tab()
        form = tab.layout()
        boundary_widget = QWidget()
        boundary_layout = QVBoxLayout(boundary_widget)
        boundary_layout.setContentsMargins(0, 0, 0, 0)
        self.boundary_layers = QListWidget()
        self.boundary_layers.setMinimumHeight(115)
        refresh_layers = QPushButton("Refresh boundary layers")
        refresh_layers.clicked.connect(self._refresh_boundary_layers)
        boundary_layout.addWidget(self.boundary_layers)
        boundary_layout.addWidget(refresh_layers)
        form.addRow("Field boundary layers (check one or more)", boundary_widget)
        # Kept as a compatibility alias for older presets and tests. The run path
        # uses the checked layer list and builds one normalized temporary layer.
        self.input_layer = None
        self.field_id_field = QComboBox()
        self.field_name_field = QComboBox()
        self.farm_name_field = QComboBox()
        self.grower_name_field = QComboBox()
        for combo, label in (
            (self.field_id_field, "Field ID column"),
            (self.field_name_field, "Field name column"),
            (self.farm_name_field, "Farm name column"),
            (self.grower_name_field, "Grower name column"),
        ):
            combo.setEditable(False)
            form.addRow(label, combo)
        self.boundary_layers.itemChanged.connect(self._boundary_selection_changed)
        self._refresh_boundary_layers()
        self.unit_system = QComboBox()
        self.unit_system.addItems(["Imperial", "Metric"])
        form.addRow("Unit system", self.unit_system)
        self.years = QLineEdit(str(datetime.now().year))
        self.years.setVisible(False)
        year_widget = QWidget()
        year_layout = QGridLayout(year_widget)
        year_layout.setContentsMargins(0, 0, 0, 0)
        self.year_buttons = {}
        current_year = datetime.now().year
        for index, year in enumerate(range(current_year, current_year - 10, -1)):
            button = QPushButton(str(year))
            button.setCheckable(True)
            button.setChecked(year == current_year)
            button.toggled.connect(self._sync_year_text_from_buttons)
            self.year_buttons[year] = button
            year_layout.addWidget(button, index // 5, index % 5)
        form.addRow("Crop years (select up to 10)", year_widget)
        self.years.textChanged.connect(self._sync_year_buttons_from_text)
        data_type_widget = QWidget()
        data_type_layout = QGridLayout(data_type_widget)
        data_type_layout.setContentsMargins(0, 0, 0, 0)
        for index, checkbox in enumerate(
            (
                self.create_soil,
                self.create_planting,
                self.create_applications,
                self.create_yield,
            )
        ):
            data_type_layout.addWidget(checkbox, 0, index)
        select_all = QPushButton("Select all")
        select_none = QPushButton("Clear all")
        select_all.clicked.connect(lambda: self._set_all_data_types(True))
        select_none.clicked.connect(lambda: self._set_all_data_types(False))
        data_type_layout.addWidget(select_all, 1, 0, 1, 2)
        data_type_layout.addWidget(select_none, 1, 2, 1, 2)
        form.addRow("Data to create", data_type_widget)
        self.timezone = QComboBox()
        self.timezone.addItem("Not specified", "")
        preferred_zones = [
            ("US Central Time (America/Chicago)", "America/Chicago"),
            ("US Eastern Time (America/New_York)", "America/New_York"),
            ("US Eastern Time (America/Indianapolis)", "America/Indianapolis"),
            ("US Mountain Time (America/Denver)", "America/Denver"),
            ("US Mountain Time - no DST (America/Phoenix)", "America/Phoenix"),
            ("US Pacific Time (America/Los_Angeles)", "America/Los_Angeles"),
            ("UTC", "UTC"),
        ]
        zones = sorted(available_timezones())
        preferred_values = {zone for _label, zone in preferred_zones}
        for label, zone in preferred_zones:
            self.timezone.addItem(label, zone)
        for zone in zones:
            if zone not in preferred_values:
                self.timezone.addItem(zone, zone)
        self.timezone.setCurrentIndex(self.timezone.findData("America/Chicago"))
        form.addRow("Machine timestamp timezone", self.timezone)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2_147_483_647)
        self.seed.setSpecialValueText("Random")
        form.addRow("Master random seed", self.seed)
        recipe_row = QWidget()
        recipe_layout = QHBoxLayout(recipe_row)
        recipe_layout.setContentsMargins(0, 0, 0, 0)
        load_recipe = QPushButton("Load recipe…")
        save_recipe = QPushButton("Save recipe…")
        load_recipe.clicked.connect(self._load_recipe)
        save_recipe.clicked.connect(self._save_recipe)
        recipe_layout.addWidget(load_recipe)
        recipe_layout.addWidget(save_recipe)
        recipe_layout.addStretch(1)
        form.addRow("Configuration recipe", recipe_row)
        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        self.output_directory = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        folder_layout.addWidget(self.output_directory, 1)
        folder_layout.addWidget(browse)
        self.output_directory.setPlaceholderText(
            "Required: choose where generated run folders will be saved"
        )
        form.insertRow(0, "Parent output directory (required)", folder_row)
        note = QLabel(
            "If the selected layer has selected polygons, only those features are processed. "
            "Limits: 20 fields, 5,000 acres, and 10 years."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.tabs.addTab(tab, "General")

    def _build_crops(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        settings = QWidget()
        form = QFormLayout(settings)
        layout.addWidget(settings)
        # Compatibility-only transport controls. They are deliberately not added
        # to the interactive form; this workflow always uses the USDA API.
        self.crop_mode = QComboBox()
        self.crop_mode.addItem("Automatic CDL")
        self.manual_crop = QComboBox()
        self.manual_crop.addItems(CreateFakeYieldAlgorithm.CROP_OPTIONS)
        self.local_cdl = QLineEdit()
        self.cdl_cache = QLineEdit()
        refresh = QPushButton("Pull Crops from USDA CDL")
        refresh.clicked.connect(self._refresh_crop_review)
        form.addRow(refresh)
        self.crop_review_table = QTableWidget(0, 6)
        self.crop_review_table.setHorizontalHeaderLabels(
            [
                "Field",
                "Year",
                "Crop",
                "Dominance",
                "Source",
                "Status",
            ]
        )
        self.crop_review_table.setAlternatingRowColors(True)
        self.crop_review_table.setMinimumHeight(220)
        self.crop_review_table.setColumnWidth(2, 150)
        self.crop_review_table.setColumnWidth(4, 150)
        layout.addWidget(self.crop_review_table, 1)
        note = QLabel(
            "The button pulls crop classifications from the USDA CroplandCROS API. "
            "If a selected year is not available, the tool estimates it from nearby "
            "API years and labels the source as rotation_inference. Field geometry is "
            "not uploaded; only a bounding rectangle is requested. Use the Crop "
            "dropdown in any row to replace the suggested crop."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self._crop_review_signature_value = None
        self._crop_suggestions = {}
        self._crop_row_by_key = {}
        self._crop_review_layer = None
        self.tabs.addTab(tab, "Crops")

    @staticmethod
    def _selected_features(layer):
        return (
            list(layer.selectedFeatures())
            if layer.selectedFeatureCount() > 0
            else list(layer.getFeatures())
        )

    def _update_field_mapping_choices(self, layer):
        field_names = sorted(
            {
                name
                for selected_layer in self._selected_boundary_layers()
                for name in selected_layer.fields().names()
            },
            key=str.casefold,
        )
        for combo in (
            self.field_id_field,
            self.field_name_field,
            self.farm_name_field,
            self.grower_name_field,
        ):
            previous = self._mapping_field(combo)
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("(Auto-detect)", "")
            for field_name in field_names:
                combo.addItem(field_name, field_name)
            self._set_mapping_field(combo, previous)
            combo.blockSignals(False)

    @staticmethod
    def _mapping_field(combo):
        text = combo.currentText().strip()
        indexed_text = combo.itemText(combo.currentIndex()) if combo.currentIndex() >= 0 else ""
        if combo.isEditable() and text != indexed_text:
            return "" if text == "(Auto-detect)" else text
        data = combo.currentData()
        if data is not None:
            return str(data)
        return "" if text == "(Auto-detect)" else text

    @staticmethod
    def _set_mapping_field(combo, field_name):
        value = str(field_name or "").strip()
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
        elif value:
            combo.addItem(value, value)
            combo.setCurrentIndex(combo.count() - 1)
        else:
            combo.setCurrentIndex(0)

    def _field_mapping(self):
        return {
            "field_id": self._mapping_field(self.field_id_field),
            "field_name": self._mapping_field(self.field_name_field),
            "farm_name": self._mapping_field(self.farm_name_field),
            "grower_name": self._mapping_field(self.grower_name_field),
        }

    def _crop_review_signature(self):
        layers = self._selected_boundary_layers()
        if not layers:
            return None
        layer_signature = []
        for layer in layers:
            feature_ids = (
                sorted(int(fid) for fid in layer.selectedFeatureIds())
                if layer.selectedFeatureCount() > 0
                else sorted(int(feature.id()) for feature in layer.getFeatures())
            )
            layer_signature.append((layer.id(), tuple(feature_ids)))
        return (
            tuple(layer_signature),
            self._years_text(),
            tuple(sorted(self._field_mapping().items())),
        )

    @staticmethod
    def _readonly_item(value):
        item = QTableWidgetItem(str(value))
        item.setFlags(item.flags() & ~QT_ITEM_IS_EDITABLE)
        return item

    def _refresh_crop_review(self):
        try:
            layer = self._combined_boundary_layer()
            years = parse_years(self._years_text())
            features = self._selected_features(layer)
            if not features:
                raise ValueError("No field features were supplied")
            if len(features) > 20:
                raise ValueError("The crop review supports at most 20 fields")
            feedback = QgsProcessingFeedback()
            QApplication.setOverrideCursor(QT_WAIT_CURSOR)
            suggestions, issues = suggest_api_field_year_assignments(
                features,
                layer.crs(),
                QgsProject.instance().transformContext(),
                years,
                CreateFakeYieldAlgorithm.CROP_OPTIONS,
                feedback,
            )
        except Exception as error:
            QMessageBox.warning(self, "Crop lookup failed", str(error))
            return False
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()

        self.crop_review_table.setRowCount(0)
        self._crop_suggestions = suggestions
        self._crop_row_by_key = {}
        self._crop_review_layer = layer
        for field_index, _feature in enumerate(features, start=1):
            field_id = f"Field_{field_index:03d}"
            identity = feature_field_identity(
                _feature,
                field_index,
                {
                    "field_id": "field_id",
                    "field_name": "field_name",
                    "farm_name": "farm_name",
                    "grower_name": "grower_name",
                },
            )
            for year in years:
                row = self.crop_review_table.rowCount()
                self.crop_review_table.insertRow(row)
                assignment = suggestions.get((field_id, year))
                key = (field_id, year)
                self._crop_row_by_key[key] = row
                field_item = self._readonly_item(identity["field_id"])
                field_item.setData(QT_USER_ROLE, field_id)
                self.crop_review_table.setItem(row, 0, field_item)
                self.crop_review_table.setItem(row, 1, self._readonly_item(year))
                crop_choice = QComboBox()
                if assignment is None or not assignment.crop_name:
                    crop_choice.addItem("Select crop…", "")
                for crop_name in CreateFakeYieldAlgorithm.CROP_OPTIONS:
                    crop_choice.addItem(crop_name, crop_name)
                if assignment is not None and assignment.crop_name:
                    crop_choice.setCurrentIndex(
                        crop_choice.findData(assignment.crop_name)
                    )
                crop_choice.currentTextChanged.connect(
                    lambda crop, assignment_key=key: self._crop_choice_changed(
                        assignment_key, crop
                    )
                )
                self.crop_review_table.setCellWidget(row, 2, crop_choice)
                self.crop_review_table.setItem(
                    row,
                    3,
                    self._readonly_item(
                        f"{assignment.crop_pct:.1f}%" if assignment else "—"
                    ),
                )
                self.crop_review_table.setItem(
                    row,
                    4,
                    self._readonly_item(
                        assignment.crop_source if assignment else "—"
                    ),
                )
                self.crop_review_table.setItem(
                    row,
                    5,
                    self._readonly_item(
                        assignment.status if assignment else "lookup_failed"
                    ),
                )
        self._crop_review_signature_value = self._crop_review_signature()
        return True

    def _reviewed_crop_overrides(self, require_review=False):
        return ""

    def _crop_choice_changed(self, key, crop_name):
        crop = str(crop_name or "").strip()
        if not crop:
            self._crop_suggestions.pop(key, None)
            return
        assignment = self._crop_suggestions.get(key)
        if assignment is None:
            assignment = CropAssignment(
                crop_name=crop,
                crop_code=None,
                crop_pct=0.0,
                crop_source="user_override",
                crop_source_year=int(key[1]),
                crop_resolution=None,
                crop_lookup_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                crop_overridden=True,
                cdl_class_name=None,
                status="user_selected",
                review_required=False,
                valid_agricultural_pixels=0,
                total_pixels=0,
            )
        else:
            assignment = replace(
                assignment,
                crop_name=crop,
                crop_source="user_override",
                crop_overridden=True,
                status="user_selected",
                review_required=False,
            )
        self._crop_suggestions[key] = assignment
        row = self._crop_row_by_key.get(key)
        if row is not None:
            self.crop_review_table.item(row, 4).setText("user_override")
            self.crop_review_table.item(row, 5).setText("user_selected")
        self.execute_button.setEnabled(False)

    def _crop_assignments_json(self, require_complete=False):
        if self._crop_review_signature_value != self._crop_review_signature():
            if require_complete:
                raise ValueError("Select Pull Crops from USDA CDL after changing fields or years")
            return ""
        years = parse_years(self._years_text())
        field_count = int(self._crop_review_layer.featureCount())
        expected = {
            (f"Field_{field_index:03d}", year)
            for field_index in range(1, field_count + 1)
            for year in years
        }
        missing = sorted(expected - set(self._crop_suggestions))
        if require_complete and missing:
            raise ValueError(
                "USDA crop lookup and rotation inference could not resolve: "
                + ", ".join(f"{field_id} {year}" for field_id, year in missing)
            )
        return json.dumps(
            {
                f"{field_id}:{year}": assignment.to_dict()
                for (field_id, year), assignment in sorted(self._crop_suggestions.items())
                if (field_id, year) in expected
            },
            separators=(",", ":"),
        )

    def _build_soil(self):
        tab, form = self._scroll_form()
        defaults = default_soil_settings(0)
        self.soil_first_year = QComboBox()
        self.soil_final_year = QComboBox()
        form.addRow("First sampling year", self.soil_first_year)
        form.addRow("Final sampling year", self.soil_final_year)
        self.soil_interval = QSpinBox()
        self.soil_interval.setRange(1, 25)
        self.soil_interval.setValue(3)
        form.addRow("Sampling interval (years)", self.soil_interval)
        self._refresh_soil_year_choices()
        self.soil_placement = self._combo(SOIL_PLACEMENTS, defaults["placement"])
        form.addRow("Point placement", self.soil_placement)
        self.soil_density = self._double(defaults["sample_density"], 0.25, 50, 4)
        form.addRow("Sample density (acres/point or ha/point)", self.soil_density)
        self.soil_boundary_setback = self._double(
            defaults["boundary_setback"], 0, 5000, 2
        )
        form.addRow(
            "Boundary setback for sample points (ft or m)",
            self.soil_boundary_setback,
        )
        self.soil_rotation = self._double(defaults["grid_rotation"], -180, 180, 2)
        form.addRow("Regular-grid rotation (degrees)", self.soil_rotation)
        self.soil_offset_x = self._double(defaults["grid_offset_x"], -100, 100, 2)
        self.soil_offset_y = self._double(defaults["grid_offset_y"], -100, 100, 2)
        form.addRow("Grid X offset (% spacing)", self.soil_offset_x)
        form.addRow("Grid Y offset (% spacing)", self.soil_offset_y)
        self.soil_depth = QLineEdit(defaults["sample_depth"])
        self.soil_lab = QLineEdit(defaults["lab_name"])
        form.addRow("Sample depth", self.soil_depth)
        form.addRow("Lab name", self.soil_lab)
        self.soil_fertility = self._combo(LEVELS, defaults["fertility_level"])
        self.soil_variability = self._combo(LEVELS, defaults["variability_level"])
        form.addRow("Fertility level", self.soil_fertility)
        form.addRow("Variability level", self.soil_variability)
        self.soil_p_unit = self._combo(["ppm", "lb/acre"], defaults["p_unit"])
        self.soil_k_unit = self._combo(["ppm", "lb/acre"], defaults["k_unit"])
        form.addRow("Phosphorus unit", self.soil_p_unit)
        form.addRow("Potassium unit", self.soil_k_unit)
        self.soil_date = QLineEdit(defaults["sample_date"])
        self.soil_date_window = QSpinBox()
        self.soil_date_window.setRange(0, 90)
        self.soil_date_window.setValue(defaults["date_window"])
        form.addRow("Default sampling date (MM-DD)", self.soil_date)
        form.addRow("Random date window (+/- days)", self.soil_date_window)
        self.soil_unattributed = QCheckBox("Create locations without nutrient columns")
        form.addRow(self.soil_unattributed)
        self.soil_surface = QCheckBox("Create interpolated polygon-grid surface")
        self.soil_surface.setChecked(defaults["create_surface"])
        form.addRow(self.soil_surface)
        self.soil_surface_grid = self._double(defaults["surface_grid_size"], 5, 1000, 3)
        form.addRow("Surface grid size (ft or m)", self.soil_surface_grid)
        self.soil_interpolation = self._combo(
            INTERPOLATION_METHODS, defaults["interpolation_method"]
        )
        form.addRow("Interpolation method", self.soil_interpolation)
        self.soil_kriging_model = self._combo(KRIGING_MODELS, defaults["kriging_model"])
        self.soil_kriging_range = self._double(defaults["kriging_range"], 0, 100000, 3)
        self.soil_kriging_nugget = self._double(defaults["kriging_nugget"], 0, 1, 3)
        self.soil_max_neighbors = QSpinBox()
        self.soil_max_neighbors.setRange(1, 100)
        self.soil_max_neighbors.setValue(defaults["max_neighbors"])
        self.soil_idw_power = self._double(defaults["idw_power"], 0.1, 10, 2)
        form.addRow("Kriging variogram", self.soil_kriging_model)
        form.addRow("Kriging range (0 = automatic; ft or m)", self.soil_kriging_range)
        form.addRow("Kriging relative nugget", self.soil_kriging_nugget)
        form.addRow("Maximum interpolation neighbors", self.soil_max_neighbors)
        form.addRow("IDW power / fallback power", self.soil_idw_power)
        self.soil_unattributed.toggled.connect(self._toggle_soil_surface)
        self.tabs.addTab(tab, "Soil Tests")

    def _toggle_soil_surface(self, unattributed):
        if unattributed:
            self.soil_surface.setChecked(False)
        self.soil_surface.setEnabled(not unattributed)

    def _build_planting(self):
        tab, form = self._scroll_form()
        defaults = default_planting_settings(0)
        self.planting_point_output = self._combo(
            PLANTING_POINT_OUTPUTS, defaults["point_output"]
        )
        form.addRow("Point records", self.planting_point_output)
        self.planter_width = self._double(defaults["planter_width"], 1, 200, 3)
        self.planter_rows = QSpinBox()
        self.planter_rows.setRange(1, 120)
        self.planter_rows.setValue(defaults["row_units"])
        self.planter_row_spacing = self._double(defaults["row_spacing"], 5, 120, 3)
        form.addRow("Planter width (ft or m)", self.planter_width)
        form.addRow("Row units", self.planter_rows)
        form.addRow("Row spacing (in or cm)", self.planter_row_spacing)
        self.planting_crop_tabs = QTabWidget()
        self.planting_crop_tabs.setMinimumHeight(250)
        self.planting_crop_controls = {}
        for crop_name, profile in defaults["crop_profiles"].items():
            crop_tab = QWidget()
            crop_form = QFormLayout(crop_tab)
            minimum = self._double(profile["min_population"], 0, 50_000_000, 1)
            target = self._double(profile["target_population"], 100, 50_000_000, 1)
            maximum = self._double(profile["max_population"], 1, 50_000_000, 1)
            depth = self._double(profile["seed_depth"], 0.1, 25.4, 3)
            month, day = (int(value) for value in profile["planting_date"].split("-"))
            planting_date = QDateEdit(QDate(2000, month, day))
            planting_date.setDisplayFormat("MM-dd")
            planting_date.setCalendarPopup(True)
            crop_form.addRow("Minimum population", minimum)
            crop_form.addRow("Target population", target)
            crop_form.addRow("Maximum population", maximum)
            crop_form.addRow("Seed depth (in or cm)", depth)
            crop_form.addRow("Typical planting date", planting_date)
            self.planting_crop_controls[crop_name] = {
                "min_population": minimum,
                "target_population": target,
                "max_population": maximum,
                "seed_depth": depth,
                "planting_date": planting_date,
            }
            self.planting_crop_tabs.addTab(crop_tab, crop_name)
        corn_controls = self.planting_crop_controls["Corn"]
        self.planting_min_population = corn_controls["min_population"]
        self.planting_target_population = corn_controls["target_population"]
        self.planting_max_population = corn_controls["max_population"]
        self.planting_seed_depth = corn_controls["seed_depth"]
        form.addRow("Crop-specific planting defaults", self.planting_crop_tabs)
        self.planting_speed = self._double(defaults["nominal_speed"], 0.1, 60, 3)
        self.planting_interval = self._double(defaults["logging_interval"], 0.1, 60, 2)
        self.planting_headland_passes = QSpinBox()
        self.planting_headland_passes.setRange(0, 20)
        self.planting_headland_passes.setValue(defaults["headland_passes"])
        form.addRow("Nominal speed (mph or km/h)", self.planting_speed)
        form.addRow("Logging interval (seconds)", self.planting_interval)
        form.addRow("Headland planter passes", self.planting_headland_passes)
        self.planting_direction = self._combo(
            COMPLETE_DIRECTION_MODES, defaults["direction_mode"]
        )
        self.planting_bearing = self._double(defaults["manual_bearing"], 0, 359.999, 3)
        form.addRow("Travel direction", self.planting_direction)
        form.addRow("Manual bearing", self.planting_bearing)
        self.planting_date_window = QSpinBox()
        self.planting_date_window.setRange(0, 90)
        self.planting_date_window.setValue(defaults["date_window"])
        form.addRow("Random date window (+/- days)", self.planting_date_window)
        self.planting_variability = self._combo(LEVELS, defaults["variability_level"])
        form.addRow("Variability level", self.planting_variability)
        self.planting_surface = QCheckBox("Create planting polygon-grid surface")
        self.planting_surface.setChecked(defaults["create_surface"])
        form.addRow(self.planting_surface)
        self.planting_surface_grid = self._double(defaults["surface_grid_size"], 5, 1000, 3)
        form.addRow("Surface grid size (ft or m)", self.planting_surface_grid)
        attribute_row = QWidget()
        attribute_layout = QGridLayout(attribute_row)
        attribute_layout.setContentsMargins(0, 0, 0, 0)
        self.planting_surface_attributes = []
        for index, name in enumerate(PLANTING_SURFACE_ATTRIBUTES):
            checkbox = QCheckBox(name)
            checkbox.setChecked(name in defaults["surface_attributes"])
            self.planting_surface_attributes.append(checkbox)
            attribute_layout.addWidget(checkbox, index // 3, index % 3)
        form.addRow("Surface attributes", attribute_row)
        metrics_note = QLabel(
            "Point logs include fake singulation, spacing quality, skips, ride quality, "
            "ground contact, furrow moisture and temperature, uniform furrow, and clean "
            "furrow metrics. Selected metrics are also available on the polygon grid."
        )
        metrics_note.setWordWrap(True)
        form.addRow(metrics_note)
        self.tabs.addTab(tab, "Planting")

    def _build_yield(self):
        tab, form = self._scroll_form()
        defaults = default_yield_settings(0)
        note = QLabel(
            "Dry-yield and moisture ranges come from each reviewed field-year crop profile. "
            "Enable the table below to override those ranges for any crop used in the run."
        )
        note.setWordWrap(True)
        form.addRow(note)
        self.customize_yield_profiles = QCheckBox(
            "Customize per-crop dry-yield and moisture ranges"
        )
        form.addRow(self.customize_yield_profiles)
        self.yield_profile_table = QTableWidget(
            0, 7
        )
        self.yield_profile_table.setHorizontalHeaderLabels(
            [
                "Crop",
                "Yield unit",
                "Minimum yield",
                "Maximum yield",
                "Minimum moisture %",
                "Maximum moisture %",
                "Standard moisture %",
            ]
        )
        self.yield_profile_table.setAlternatingRowColors(True)
        self.yield_profile_table.setMinimumHeight(220)
        self.yield_profile_table.setMaximumHeight(270)
        self.yield_profile_table.setEnabled(False)
        self.customize_yield_profiles.toggled.connect(
            self.yield_profile_table.setEnabled
        )
        self._populate_yield_profile_table(0)
        form.addRow(self.yield_profile_table)
        self.yield_swath = self._double(defaults["swath_width"], 1, 100, 3)
        self.yield_speed = self._double(defaults["nominal_speed"], 0.1, 60, 3)
        self.yield_interval = self._double(defaults["logging_interval"], 0.1, 60, 2)
        self.yield_headland_passes = QSpinBox()
        self.yield_headland_passes.setRange(0, 20)
        self.yield_headland_passes.setValue(defaults["headland_passes"])
        self.yield_headland_penalty = self._double(defaults["headland_penalty"], 0, 75, 2)
        form.addRow("Header / swath width (ft or m)", self.yield_swath)
        form.addRow("Harvest speed (mph or km/h)", self.yield_speed)
        form.addRow("Logging interval (seconds)", self.yield_interval)
        form.addRow(
            "Headland combine passes (default matches 2 planter passes)",
            self.yield_headland_passes,
        )
        form.addRow("Headland yield penalty (%)", self.yield_headland_penalty)
        self.yield_direction = self._combo(
            COMPLETE_DIRECTION_MODES, defaults["direction_mode"]
        )
        self.yield_bearing = self._double(defaults["manual_bearing"], 0, 359.999, 3)
        form.addRow("Travel direction", self.yield_direction)
        form.addRow("Manual bearing", self.yield_bearing)
        self.yield_date = QLineEdit(defaults["harvest_date"])
        self.yield_date_window = QSpinBox()
        self.yield_date_window.setRange(0, 90)
        self.yield_date_window.setValue(defaults["date_window"])
        form.addRow("Default harvest date (MM-DD)", self.yield_date)
        form.addRow("Random date window (+/- days)", self.yield_date_window)
        self.yield_variability = self._combo(LEVELS, defaults["variability_level"])
        form.addRow("Variability level", self.yield_variability)
        self.yield_surface = QCheckBox("Create yield polygon-grid surface")
        self.yield_surface.setChecked(defaults["create_surface"])
        form.addRow(self.yield_surface)
        self.yield_surface_grid = self._double(defaults["surface_grid_size"], 5, 1000, 3)
        form.addRow("Surface grid size (ft or m)", self.yield_surface_grid)
        for control in (
            self.planter_width,
            self.planting_headland_passes,
            self.yield_swath,
        ):
            control.valueChanged.connect(self._sync_yield_headland_passes)
        self._sync_yield_headland_passes()
        self.tabs.addTab(tab, "Yield")

    def _sync_yield_headland_passes(self, _value=None):
        """Match the default harvested headland depth to the planted headland."""

        planter_depth = (
            self.planter_width.value() * self.planting_headland_passes.value()
        )
        combine_passes = (
            int(math.ceil(planter_depth / max(0.001, self.yield_swath.value())))
            if planter_depth > 0
            else 0
        )
        self.yield_headland_passes.setValue(min(20, combine_passes))

    def _populate_yield_profile_table(self, unit_index, overrides=None):
        overrides = overrides or {}
        self.yield_profile_table.setRowCount(0)
        for crop_name in CreateFakeYieldAlgorithm.CROP_OPTIONS:
            minimum, maximum, standard_moisture, yield_unit = (
                CreateFakeYieldAlgorithm.CROP_PROFILES[crop_name]
            )
            if int(unit_index) == 1:
                minimum, maximum, yield_unit = metric_yield_profile(
                    crop_name, minimum, maximum, yield_unit
                )
            values = overrides.get(crop_name) or {
                "min_yield": minimum,
                "max_yield": maximum,
                "min_moisture": max(0.0, standard_moisture - 3.0),
                "max_moisture": min(99.0, standard_moisture + 8.0),
                "standard_moisture": standard_moisture,
            }
            row = self.yield_profile_table.rowCount()
            self.yield_profile_table.insertRow(row)
            self.yield_profile_table.setItem(row, 0, self._readonly_item(crop_name))
            self.yield_profile_table.setItem(row, 1, self._readonly_item(yield_unit))
            for column, key in enumerate(
                (
                    "min_yield",
                    "max_yield",
                    "min_moisture",
                    "max_moisture",
                    "standard_moisture",
                ),
                start=2,
            ):
                self.yield_profile_table.setItem(
                    row, column, QTableWidgetItem(f"{float(values[key]):.8g}")
                )
        self.yield_profile_table.resizeColumnsToContents()

    def _yield_profile_overrides(self):
        if not self.customize_yield_profiles.isChecked():
            return {}
        overrides = {}
        keys = (
            "min_yield",
            "max_yield",
            "min_moisture",
            "max_moisture",
            "standard_moisture",
        )
        for row in range(self.yield_profile_table.rowCount()):
            crop_name = self.yield_profile_table.item(row, 0).text()
            values = {}
            for column, key in enumerate(keys, start=2):
                item = self.yield_profile_table.item(row, column)
                try:
                    values[key] = float(item.text())
                except (AttributeError, TypeError, ValueError) as error:
                    raise ValueError(
                        f"{crop_name} {self.yield_profile_table.horizontalHeaderItem(column).text()} "
                        "must be numeric"
                    ) from error
            overrides[crop_name] = values
        return overrides

    @staticmethod
    def _combo(options, selected):
        combo = QComboBox()
        combo.addItems(options)
        index = combo.findText(str(selected))
        combo.setCurrentIndex(max(0, index))
        return combo

    @staticmethod
    def _set_combo_text(combo, value, label):
        index = combo.findText(str(value))
        if index < 0:
            raise ValueError(f"Unsupported {label}: {value}")
        combo.setCurrentIndex(index)

    def _dialog_recipe(self):
        """Return the reusable, pre-run dialog configuration."""

        crop_overrides = self._reviewed_crop_overrides(require_review=False)
        return {
            "schema_version": 1,
            "recipe_type": "fake_farm_data_generator_complete_dialog",
            "fake_data": True,
            "fake_warning": FAKE_WARNING,
            "generator_name": "Fake Farm Data Generator",
            "generator_version": "1.0.0",
            "unit_system": self.unit_system.currentText(),
            "years": self._years_text(),
            "timezone": normalize_timezone_label(self._timezone_text()),
            "master_seed": self.seed.value(),
            "output_directory": self.output_directory.text().strip(),
            "field_mapping": self._field_mapping(),
            "enabled": {
                "soil": self.create_soil.isChecked(),
                "planting": self.create_planting.isChecked(),
                "applications": self.create_applications.isChecked(),
                "yield": self.create_yield.isChecked(),
            },
            "soil_interval": self.soil_interval.value(),
            "soil_first_year": str(self.soil_first_year.currentData() or ""),
            "soil_final_year": str(self.soil_final_year.currentData() or ""),
            "soil_settings": self._soil_settings(),
            "planting_settings": self._planting_settings(),
            "application_operations": self._application_rows(),
            "yield_settings": self._yield_settings(),
            "crop": {
                "source": "USDA CroplandCROS API",
                "missing_year_method": "rotation_inference",
            },
            "output_formats": [
                OUTPUT_FORMAT_OPTIONS[index]
                for index, checkbox in enumerate(self.format_checks)
                if checkbox.isChecked()
            ],
            "review_max_features": self.review_max_features.value(),
        }

    def _apply_dialog_recipe(self, payload):
        """Apply a reusable dialog recipe after validating its shape and values."""

        if not isinstance(payload, dict):
            raise ValueError("Recipe must be a JSON object")
        recipe_type = payload.get("recipe_type")
        if recipe_type in ("fake_farm_data_generator_run", None) and "data_types" in payload:
            years_value = payload.get("years", [])
            years_text = (
                ",".join(str(year) for year in years_value)
                if isinstance(years_value, list)
                else str(years_value)
            )
            payload = {
                "schema_version": payload.get("schema_version", 1),
                "recipe_type": "fake_farm_data_generator_complete_dialog",
                "unit_system": payload.get("unit_system", "Imperial"),
                "years": years_text,
                "timezone": payload.get("timezone", ""),
                "master_seed": payload.get("master_seed", 0),
                "output_directory": "",
                "field_mapping": payload.get("field_mapping", {}),
                "enabled": payload.get("data_types", {}),
                "soil_interval": payload.get("soil_interval", 3),
                "soil_first_year": payload.get("soil_first_year", ""),
                "soil_final_year": payload.get("soil_final_year", ""),
                "soil_settings": payload.get("soil_settings", {}),
                "planting_settings": payload.get("planting_settings", {}),
                "application_operations": payload.get("application_operations", []),
                "yield_settings": payload.get("yield_settings", {}),
                "crop": {
                    "lookup_mode": payload.get("crop_lookup_mode", "Manual profile"),
                    "manual_profile": payload.get("crop_profile", "Corn"),
                    "local_cdl_path": payload.get("local_cdl_path", ""),
                    "cache_directory": payload.get("cdl_cache_directory", ""),
                    "overrides_json": payload.get("crop_overrides_json", ""),
                },
                "output_formats": payload.get("output_formats", ["GeoPackage"]),
                "review_max_features": payload.get(
                    "review_max_features", DEFAULT_REVIEW_MAX_FEATURES
                ),
            }
        if payload.get("recipe_type") != "fake_farm_data_generator_complete_dialog":
            raise ValueError("This is not a Fake Farm Data Generator dialog recipe")
        if int(payload.get("schema_version", 0)) != 1:
            raise ValueError("Unsupported dialog recipe schema version")

        unit_name = str(payload.get("unit_system", "Imperial"))
        self._set_combo_text(self.unit_system, unit_name, "unit system")
        self._set_years(payload.get("years", self._years_text()))
        self._set_timezone(payload.get("timezone", ""))
        self.seed.setValue(int(payload.get("master_seed", 0)))
        self.output_directory.setText(str(payload.get("output_directory", "")))
        field_mapping = payload.get("field_mapping", {})
        if not isinstance(field_mapping, dict):
            raise ValueError("Recipe field mapping must be an object")
        for key, combo in (
            ("field_id", self.field_id_field),
            ("field_name", self.field_name_field),
            ("farm_name", self.farm_name_field),
            ("grower_name", self.grower_name_field),
        ):
            self._set_mapping_field(combo, field_mapping.get(key, ""))
        enabled = payload.get("enabled", {})
        if not isinstance(enabled, dict):
            raise ValueError("Recipe enabled settings must be an object")
        self.create_soil.setChecked(bool(enabled.get("soil", True)))
        self.create_planting.setChecked(bool(enabled.get("planting", True)))
        self.create_applications.setChecked(bool(enabled.get("applications", True)))
        self.create_yield.setChecked(bool(enabled.get("yield", True)))
        self.soil_interval.setValue(int(payload.get("soil_interval", 3)))
        for combo, value in (
            (self.soil_first_year, payload.get("soil_first_year", "")),
            (self.soil_final_year, payload.get("soil_final_year", "")),
        ):
            index = combo.findData(str(value or ""))
            combo.setCurrentIndex(index if index >= 0 else 0)

        unit_index = self.unit_system.currentIndex()
        soil = normalize_soil_settings(payload.get("soil_settings", {}), unit_index)
        planting = normalize_planting_settings(
            payload.get("planting_settings", {}), unit_index
        )
        yield_settings = normalize_yield_settings(
            payload.get("yield_settings", {}), unit_index
        )
        self._apply_soil_settings(soil)
        self._apply_planting_settings(planting)
        self._apply_yield_settings(yield_settings)

        operations = payload.get("application_operations", [])
        if not isinstance(operations, list):
            raise ValueError("Recipe application operations must be a list")
        normalize_application_operations(
            json.dumps(operations), parse_years(self._years_text())
        )
        migrated_operations = []
        for operation in operations:
            migrated = dict(operation)
            if "headland_passes" not in migrated:
                width = float(migrated.get("equipment_width", 60.0) or 60.0)
                legacy = float(migrated.pop("headland_width", width * 2) or 0.0)
                migrated["headland_passes"] = min(
                    20, int(math.ceil(legacy / max(0.001, width)))
                )
            migrated_operations.append(migrated)
        self._load_application_rows(migrated_operations)

        crop = payload.get("crop", {})
        if not isinstance(crop, dict):
            raise ValueError("Recipe crop settings must be an object")
        self.crop_mode.setCurrentIndex(0)
        overrides_text = str(crop.get("overrides_json", ""))
        self._preset_crop_overrides = parse_overrides(
            overrides_text, CreateFakeYieldAlgorithm.CROP_OPTIONS
        )
        self.crop_review_table.setRowCount(0)
        self._crop_suggestions = {}
        self._crop_review_signature_value = None

        selected_formats = payload.get("output_formats", ["GeoPackage"])
        if not isinstance(selected_formats, list):
            raise ValueError("Recipe output formats must be a list")
        invalid_formats = sorted(set(selected_formats) - set(OUTPUT_FORMAT_OPTIONS))
        if invalid_formats:
            raise ValueError(
                "Unsupported output format(s): " + ", ".join(invalid_formats)
            )
        for index, checkbox in enumerate(self.format_checks):
            checkbox.setChecked(OUTPUT_FORMAT_OPTIONS[index] in selected_formats)
        self.format_checks[0].setChecked(True)
        self.review_max_features.setValue(
            normalize_review_max_features(
                payload.get("review_max_features", DEFAULT_REVIEW_MAX_FEATURES)
            )
        )

    def _apply_soil_settings(self, settings):
        self._set_combo_text(self.soil_placement, settings["placement"], "soil placement")
        self.soil_density.setValue(settings["sample_density"])
        self.soil_boundary_setback.setValue(settings["boundary_setback"])
        self.soil_rotation.setValue(settings["grid_rotation"])
        self.soil_offset_x.setValue(settings["grid_offset_x"])
        self.soil_offset_y.setValue(settings["grid_offset_y"])
        self.soil_depth.setText(settings["sample_depth"])
        self.soil_lab.setText(settings["lab_name"])
        self._set_combo_text(self.soil_fertility, settings["fertility_level"], "fertility level")
        self._set_combo_text(self.soil_variability, settings["variability_level"], "soil variability")
        displayed_p_unit = (
            "kg/ha"
            if self.unit_system.currentIndex() == 1 and settings["p_unit"] == "lb/acre"
            else settings["p_unit"]
        )
        displayed_k_unit = (
            "kg/ha"
            if self.unit_system.currentIndex() == 1 and settings["k_unit"] == "lb/acre"
            else settings["k_unit"]
        )
        self._set_combo_text(self.soil_p_unit, displayed_p_unit, "phosphorus unit")
        self._set_combo_text(self.soil_k_unit, displayed_k_unit, "potassium unit")
        self.soil_date.setText(settings["sample_date"])
        self.soil_date_window.setValue(settings["date_window"])
        self.soil_unattributed.setChecked(settings["unattributed"])
        self.soil_surface.setChecked(settings["create_surface"])
        self.soil_surface_grid.setValue(settings["surface_grid_size"])
        self._set_combo_text(self.soil_interpolation, settings["interpolation_method"], "soil interpolation")
        self._set_combo_text(self.soil_kriging_model, settings["kriging_model"], "kriging model")
        self.soil_kriging_range.setValue(settings["kriging_range"])
        self.soil_kriging_nugget.setValue(settings["kriging_nugget"])
        self.soil_max_neighbors.setValue(settings["max_neighbors"])
        self.soil_idw_power.setValue(settings["idw_power"])

    def _apply_planting_settings(self, settings):
        self._set_combo_text(self.planting_point_output, settings["point_output"], "planting point output")
        self.planter_width.setValue(settings["planter_width"])
        self.planter_rows.setValue(settings["row_units"])
        self.planter_row_spacing.setValue(settings["row_spacing"])
        profiles = settings.get("crop_profiles", {})
        for crop_name, controls in self.planting_crop_controls.items():
            profile = profiles.get(crop_name, planting_crop_profiles(self.unit_system.currentIndex())[crop_name])
            controls["min_population"].setValue(profile["min_population"])
            controls["target_population"].setValue(profile["target_population"])
            controls["max_population"].setValue(profile["max_population"])
            controls["seed_depth"].setValue(profile["seed_depth"])
            month, day = (int(value) for value in profile["planting_date"].split("-"))
            controls["planting_date"].setDate(QDate(2000, month, day))
        self.planting_speed.setValue(settings["nominal_speed"])
        self.planting_interval.setValue(settings["logging_interval"])
        self.planting_headland_passes.setValue(settings["headland_passes"])
        self._set_combo_text(self.planting_direction, settings["direction_mode"], "planting direction")
        self.planting_bearing.setValue(settings["manual_bearing"])
        self.planting_date_window.setValue(settings["date_window"])
        self._set_combo_text(self.planting_variability, settings["variability_level"], "planting variability")
        self.planting_surface.setChecked(settings["create_surface"])
        self.planting_surface_grid.setValue(settings["surface_grid_size"])
        selected = set(settings["surface_attributes"])
        for checkbox in self.planting_surface_attributes:
            checkbox.setChecked(checkbox.text() in selected)

    def _apply_yield_settings(self, settings):
        self.yield_swath.setValue(settings["swath_width"])
        self.yield_speed.setValue(settings["nominal_speed"])
        self.yield_interval.setValue(settings["logging_interval"])
        self.yield_headland_passes.setValue(settings["headland_passes"])
        self.yield_headland_penalty.setValue(settings["headland_penalty"])
        self._set_combo_text(self.yield_direction, settings["direction_mode"], "yield direction")
        self.yield_bearing.setValue(settings["manual_bearing"])
        self.yield_date.setText(settings["harvest_date"])
        self.yield_date_window.setValue(settings["date_window"])
        self._set_combo_text(self.yield_variability, settings["variability_level"], "yield variability")
        self.yield_surface.setChecked(settings["create_surface"])
        self.yield_surface_grid.setValue(settings["surface_grid_size"])
        overrides = settings.get("profile_overrides", {})
        self.customize_yield_profiles.setChecked(bool(overrides))
        self._populate_yield_profile_table(
            self.unit_system.currentIndex(), overrides or None
        )

    def _save_recipe(self):
        try:
            recipe = self._dialog_recipe()
            parse_years(recipe["years"])
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Cannot save recipe", str(error))
            return
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save complete-run recipe",
            "fake_farm_data_recipe.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(recipe, indent=2), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, "Recipe save failed", str(error))

    def _load_recipe(self):
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Load complete-run recipe",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            self._apply_dialog_recipe(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.warning(self, "Recipe load failed", str(error))

    def _build_applications(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        note = QLabel(
            "Each row is one operation. Use All to repeat a row for every selected year. "
            "Width, speed, headland, grid size, and entered rate units follow the top-level "
            "Imperial / Metric selection. Flat rates retain realistic bounded log variation."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.application_table = QTableWidget(0, len(self.APPLICATION_COLUMNS))
        self.application_table.setHorizontalHeaderLabels(
            [label for _key, label in self.APPLICATION_COLUMNS]
        )
        self.application_table.setMinimumHeight(300)
        self.application_table.setAlternatingRowColors(True)
        layout.addWidget(self.application_table, 1)
        button_row = QHBoxLayout()
        for label, callback in (
            ("Add", self._add_application_row),
            ("Add selected years", self._add_application_year_rows),
            ("Duplicate", self._duplicate_application_row),
            ("Remove", self._remove_application_row),
            ("Move up", lambda: self._move_application_row(-1)),
            ("Move down", lambda: self._move_application_row(1)),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        self._load_application_rows([default_application_operation()])
        self.tabs.addTab(tab, "Applications")

    def _set_application_row(self, row, operation):
        combo_options = {
            "operation_type": OPERATION_TYPES,
            "rate_mode": RATE_MODES,
            "direction_mode": DIRECTION_MODES,
            "variability_level": VARIABILITY_LEVELS,
        }
        for column, (key, _label) in enumerate(self.APPLICATION_COLUMNS):
            value = operation.get(key, "")
            if key in combo_options:
                self.application_table.setCellWidget(
                    row, column, self._combo(combo_options[key], value)
                )
            elif key in {"enabled", "create_surface"}:
                item = QTableWidgetItem()
                item.setFlags(item.flags() | QT_ITEM_IS_USER_CHECKABLE)
                item.setCheckState(QT_CHECKED if bool(value) else QT_UNCHECKED)
                self.application_table.setItem(row, column, item)
            else:
                self.application_table.setItem(row, column, QTableWidgetItem(str(value)))

    def _application_row(self, row):
        operation = {}
        numeric = {
            "target_rate",
            "min_rate",
            "max_rate",
            "equipment_width",
            "nominal_speed",
            "logging_interval",
            "headland_passes",
            "manual_bearing",
            "surface_grid_size",
        }
        for column, (key, _label) in enumerate(self.APPLICATION_COLUMNS):
            widget = self.application_table.cellWidget(row, column)
            item = self.application_table.item(row, column)
            if widget is not None:
                value = widget.currentText()
            elif key in {"enabled", "create_surface"}:
                value = bool(item and item.checkState() == QT_CHECKED)
            else:
                value = item.text().strip() if item else ""
            if key in numeric:
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    pass
            elif key == "date_window":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    pass
            operation[key] = value
        return operation

    def _application_rows(self):
        return [
            self._application_row(row) for row in range(self.application_table.rowCount())
        ]

    def _load_application_rows(self, operations):
        self.application_table.setRowCount(0)
        for operation in operations:
            row = self.application_table.rowCount()
            self.application_table.insertRow(row)
            self._set_application_row(row, operation)
        if self.application_table.rowCount():
            self.application_table.selectRow(0)
        self.application_table.resizeColumnsToContents()

    def _add_application_row(self):
        operation = default_application_operation("all", self.application_table.rowCount() + 1)
        row = self.application_table.rowCount()
        self.application_table.insertRow(row)
        self._set_application_row(row, operation)
        self.application_table.selectRow(row)

    def _add_application_year_rows(self):
        try:
            years = parse_years(self._years_text())
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid years", str(error))
            return
        operations = self._application_rows()
        existing = {str(operation.get("year", "")).strip() for operation in operations}
        for year in years:
            if str(year) in existing:
                continue
            operation = default_application_operation(year, len(operations) + 1)
            operation["operation_id"] = f"APP_{year}_001"
            operations.append(operation)
        self._load_application_rows(operations)

    def _duplicate_application_row(self):
        row = self.application_table.currentRow()
        if row < 0:
            return
        operations = self._application_rows()
        duplicate = dict(operations[row])
        suffix = self.application_table.rowCount() + 1
        duplicate["operation_id"] = f"{str(duplicate['operation_id'])[:55]}_{suffix:03d}"
        operations.insert(row + 1, duplicate)
        self._load_application_rows(operations)
        self.application_table.selectRow(row + 1)

    def _remove_application_row(self):
        row = self.application_table.currentRow()
        if row >= 0:
            self.application_table.removeRow(row)

    def _move_application_row(self, offset):
        row = self.application_table.currentRow()
        destination = row + offset
        if row < 0 or destination < 0 or destination >= self.application_table.rowCount():
            return
        operations = self._application_rows()
        operations[row], operations[destination] = operations[destination], operations[row]
        self._load_application_rows(operations)
        self.application_table.selectRow(destination)

    def _soil_settings(self):
        return {
            "placement": self.soil_placement.currentText(),
            "sample_density": self.soil_density.value(),
            "boundary_setback": self.soil_boundary_setback.value(),
            "grid_rotation": self.soil_rotation.value(),
            "grid_offset_x": self.soil_offset_x.value(),
            "grid_offset_y": self.soil_offset_y.value(),
            "sample_depth": self.soil_depth.text().strip(),
            "lab_name": self.soil_lab.text().strip(),
            "fertility_level": self.soil_fertility.currentText(),
            "variability_level": self.soil_variability.currentText(),
            "p_unit": self.soil_p_unit.currentText(),
            "k_unit": self.soil_k_unit.currentText(),
            "sample_date": self.soil_date.text().strip(),
            "date_window": self.soil_date_window.value(),
            "unattributed": self.soil_unattributed.isChecked(),
            "create_surface": self.soil_surface.isChecked(),
            "surface_grid_size": self.soil_surface_grid.value(),
            "interpolation_method": self.soil_interpolation.currentText(),
            "idw_power": self.soil_idw_power.value(),
            "max_neighbors": self.soil_max_neighbors.value(),
            "kriging_model": self.soil_kriging_model.currentText(),
            "kriging_range": self.soil_kriging_range.value(),
            "kriging_nugget": self.soil_kriging_nugget.value(),
        }

    def _planting_settings(self):
        crop_profiles = {}
        for crop_name, controls in self.planting_crop_controls.items():
            date = controls["planting_date"].date()
            crop_profiles[crop_name] = {
                "min_population": controls["min_population"].value(),
                "target_population": controls["target_population"].value(),
                "max_population": controls["max_population"].value(),
                "seed_depth": controls["seed_depth"].value(),
                "planting_date": f"{date.month():02d}-{date.day():02d}",
            }
        corn = crop_profiles["Corn"]
        return {
            "point_output": self.planting_point_output.currentText(),
            "planter_width": self.planter_width.value(),
            "row_units": self.planter_rows.value(),
            "row_spacing": self.planter_row_spacing.value(),
            "target_population": corn["target_population"],
            "min_population": corn["min_population"],
            "max_population": corn["max_population"],
            "seed_depth": corn["seed_depth"],
            "nominal_speed": self.planting_speed.value(),
            "logging_interval": self.planting_interval.value(),
            "headland_passes": self.planting_headland_passes.value(),
            "direction_mode": self.planting_direction.currentText(),
            "manual_bearing": self.planting_bearing.value(),
            "planting_date": corn["planting_date"],
            "date_window": self.planting_date_window.value(),
            "variability_level": self.planting_variability.currentText(),
            "create_surface": self.planting_surface.isChecked(),
            "surface_grid_size": self.planting_surface_grid.value(),
            "surface_attributes": [
                checkbox.text()
                for checkbox in self.planting_surface_attributes
                if checkbox.isChecked()
            ],
            "crop_profiles": crop_profiles,
        }

    def _yield_settings(self):
        return {
            "swath_width": self.yield_swath.value(),
            "nominal_speed": self.yield_speed.value(),
            "logging_interval": self.yield_interval.value(),
            "headland_passes": self.yield_headland_passes.value(),
            "headland_penalty": self.yield_headland_penalty.value(),
            "direction_mode": self.yield_direction.currentText(),
            "manual_bearing": self.yield_bearing.value(),
            "harvest_date": self.yield_date.text().strip(),
            "date_window": self.yield_date_window.value(),
            "variability_level": self.yield_variability.currentText(),
            "create_surface": self.yield_surface.isChecked(),
            "surface_grid_size": self.yield_surface_grid.value(),
            "profile_overrides": self._yield_profile_overrides(),
        }

    def _convert_yield_profile_units(self, new_index):
        old_index = getattr(self, "_yield_profile_unit_index", new_index)
        if new_index == old_index:
            return
        to_metric = new_index == 1
        for row in range(self.yield_profile_table.rowCount()):
            crop_name = self.yield_profile_table.item(row, 0).text()
            _minimum, _maximum, _moisture, imperial_unit = (
                CreateFakeYieldAlgorithm.CROP_PROFILES[crop_name]
            )
            factor, _unused, metric_unit = metric_yield_profile(
                crop_name, 1.0, 1.0, imperial_unit
            )
            scale = factor if to_metric else 1.0 / factor
            for column in (2, 3):
                item = self.yield_profile_table.item(row, column)
                item.setText(f"{float(item.text()) * scale:.8g}")
            self.yield_profile_table.item(row, 1).setText(
                metric_unit if to_metric else imperial_unit
            )
        self._yield_profile_unit_index = new_index

    def _convert_application_units(self, new_index):
        old_index = getattr(self, "_application_unit_index", new_index)
        if new_index == old_index:
            return
        operations = self._application_rows()
        to_metric = new_index == 1
        distance_factor = 0.3048 if to_metric else 1.0 / 0.3048
        speed_factor = 1.609344 if to_metric else 1.0 / 1.609344
        for operation in operations:
            for key in ("equipment_width", "surface_grid_size"):
                if isinstance(operation.get(key), (int, float)):
                    operation[key] = round(operation[key] * distance_factor, 6)
            if isinstance(operation.get("nominal_speed"), (int, float)):
                operation["nominal_speed"] = round(
                    operation["nominal_speed"] * speed_factor, 6
                )
            rate_unit = str(operation.get("rate_unit", "")).strip().casefold()
            if to_metric and rate_unit == "lb/acre":
                operation["rate_unit"] = "kg/ha"
                for key in ("target_rate", "min_rate", "max_rate"):
                    operation[key] = round(float(operation[key]) * 1.120851156, 6)
            elif not to_metric and rate_unit == "kg/ha":
                operation["rate_unit"] = "lb/acre"
                for key in ("target_rate", "min_rate", "max_rate"):
                    operation[key] = round(float(operation[key]) / 1.120851156, 6)
        self._application_unit_index = new_index
        self._load_application_rows(operations)

    @staticmethod
    def _scale_control(control, factor):
        control.setValue(round(control.value() * factor, 6))

    def _convert_unit_system(self, new_index):
        old_index = getattr(self, "_unit_index", new_index)
        if new_index == old_index:
            return
        to_metric = new_index == 1
        distance_factor = 0.3048 if to_metric else 1.0 / 0.3048
        small_distance_factor = 2.54 if to_metric else 1.0 / 2.54
        speed_factor = 1.609344 if to_metric else 1.0 / 1.609344
        population_factor = 2.4710538147 if to_metric else 1.0 / 2.4710538147
        area_factor = 0.40468564224 if to_metric else 1.0 / 0.40468564224

        self._convert_application_units(new_index)
        self._convert_yield_profile_units(new_index)
        self._scale_control(self.soil_density, area_factor)
        for control in (
            self.soil_boundary_setback,
            self.soil_surface_grid,
            self.soil_kriging_range,
        ):
            self._scale_control(control, distance_factor)
        if to_metric and self.soil_depth.text().strip() == "0-8 inches":
            self.soil_depth.setText("0-20 cm")
        elif not to_metric and self.soil_depth.text().strip() == "0-20 cm":
            self.soil_depth.setText("0-8 inches")
        for combo in (self.soil_p_unit, self.soil_k_unit):
            combo.setItemText(1, "kg/ha" if to_metric else "lb/acre")

        for control in (self.planter_width, self.planting_surface_grid):
            self._scale_control(control, distance_factor)
        self._scale_control(self.planter_row_spacing, small_distance_factor)
        for controls in self.planting_crop_controls.values():
            self._scale_control(controls["seed_depth"], small_distance_factor)
            for name in ("target_population", "min_population", "max_population"):
                self._scale_control(controls[name], population_factor)
        self._scale_control(self.planting_speed, speed_factor)

        for control in (self.yield_swath, self.yield_surface_grid):
            self._scale_control(control, distance_factor)
        self._scale_control(self.yield_speed, speed_factor)
        self._unit_index = new_index

    def _build_outputs(self):
        tab = self._tab()
        form = tab.layout()
        self.format_checks = []
        for index, name in enumerate(OUTPUT_FORMAT_OPTIONS):
            checkbox = QCheckBox(name)
            checkbox.setChecked(index == 0)
            checkbox.setEnabled(index != 0)
            self.format_checks.append(checkbox)
            form.addRow(checkbox)
        self.review_max_features = QSpinBox()
        self.review_max_features.setRange(
            MIN_REVIEW_MAX_FEATURES, MAX_REVIEW_MAX_FEATURES
        )
        self.review_max_features.setSingleStep(1000)
        self.review_max_features.setValue(DEFAULT_REVIEW_MAX_FEATURES)
        self.review_max_features.setToolTip(
            "Maximum features serialized from each high-volume layer. Every soil-test "
            "point is included regardless of this setting. Exported datasets are never sampled."
        )
        form.addRow("Review features per high-volume layer", self.review_max_features)
        self.summary = QLabel(
            "Every successful run creates a portable HTML review with independent left/right "
            "layer selectors and a comparison divider. Choose Review Run to validate the "
            "configuration and populate the review page before generation."
        )
        self.summary.setWordWrap(True)
        form.addRow(self.summary)
        self.preflight_review = QTextEdit()
        self.preflight_review.setReadOnly(True)
        self.preflight_review.setMinimumHeight(285)
        self.preflight_review.setPlainText(
            "No reviewed configuration yet. Choose Review Run after selecting fields, years, "
            "data types, crop settings, and outputs."
        )
        form.addRow("Preflight review", self.preflight_review)
        review_actions = QWidget()
        review_actions_layout = QHBoxLayout(review_actions)
        review_actions_layout.setContentsMargins(0, 0, 0, 0)
        self.refresh_review_button = QPushButton("Refresh Review")
        self.refresh_review_button.clicked.connect(self.review_generation)
        review_actions_layout.addWidget(self.refresh_review_button)
        self.execute_button = QPushButton("Run Reviewed Configuration")
        self.execute_button.setEnabled(False)
        self.execute_button.clicked.connect(lambda: self.run_generation(False))
        review_actions_layout.addWidget(self.execute_button)
        form.addRow(review_actions)
        self.open_output = QPushButton("Open last output folder")
        self.open_output.setEnabled(False)
        self.open_output.clicked.connect(self._open_output)
        form.addRow(self.open_output)
        self.tabs.addTab(tab, "Outputs and Review")

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select parent output directory")
        if folder:
            self.output_directory.setText(folder)

    def _open_output(self):
        if self.output_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_folder)))

    @staticmethod
    def _snapshot_generation_input(layer):
        target = QgsProcessingUtils.generateTempFilename(
            "fake_farm_complete_input.gpkg"
        )
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "fake_field_boundaries"
        error, actual_file, _actual_layer, error_message = (
            QgsVectorFileWriter.writeAsVectorFormatV3(
                layer,
                target,
                QgsProject.instance().transformContext(),
                options,
            )
        )
        if int(error) != 0:
            raise ValueError(
                "Could not prepare the selected fields for the isolated worker: "
                + str(error_message or error)
            )
        return str(actual_file or target)

    @staticmethod
    def _qgis_process_program():
        for executable_name in ("qgis_process", "qgis_process.exe"):
            found = QStandardPaths.findExecutable(executable_name)
            if found:
                return found
        app_dir = Path(QgsApplication.applicationDirPath())
        prefix = Path(QgsApplication.prefixPath())
        candidates = (
            app_dir / "qgis_process.exe",
            app_dir / "qgis_process",
            app_dir / "bin" / "qgis_process",
            prefix / "bin" / "qgis_process.exe",
            prefix / "bin" / "qgis_process",
        )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        raise ValueError(
            "Could not find qgis_process. Install it with QGIS or repair the QGIS installation."
        )

    @staticmethod
    def _qgis_process_arguments(parameters):
        arguments = [
            "--verbose",
            "run",
            "fake_farm_data_generator:create_complete_fake_farm_dataset",
            "--",
        ]
        for name, value in parameters.items():
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                # qgis_process accepts multi-value enum parameters as one
                # comma-separated value. Repeating the same parameter name
                # makes QGIS reject OUTPUT_FORMATS before generation starts.
                serialized = ",".join(
                    "1" if item is True else "0" if item is False else str(item)
                    for item in value
                )
            else:
                serialized = "1" if value is True else "0" if value is False else str(value)
            arguments.append(f"{name}={serialized}")
        return arguments

    def _set_generation_controls_enabled(self, enabled):
        self.run_button.setEnabled(enabled)
        self.refresh_review_button.setEnabled(enabled)
        self.execute_button.setEnabled(enabled)
        if self.close_button is not None:
            self.close_button.setEnabled(enabled)

    def _update_generation_progress_message(self, message):
        if self._generation_progress is None:
            return
        text = str(message or "").strip()
        if len(text) > 320:
            text = text[:317] + "…"
        if text:
            self._generation_messages.append(text)
            self._generation_progress.setLabelText(text)

    def _read_generation_output(self):
        process = self._generation_process
        if process is None:
            return
        chunk = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not chunk:
            return
        self._generation_output += chunk
        overall_markers = re.findall(
            r"FFDG_OVERALL_PROGRESS\|(\d{1,3})\|([^\r\n]+)",
            self._generation_output,
        )
        if overall_markers and self._generation_progress is not None:
            percent, message = overall_markers[-1]
            value = max(0, min(100, int(percent)))
            if value > self._generation_last_progress_marker:
                self._generation_last_progress_marker = value
                self._generation_progress.setValue(
                    max(self._generation_progress.value(), value)
                )
                self._update_generation_progress_message(message)
        for line in chunk.splitlines():
            text = line.strip()
            if any(
                marker in text
                for marker in (
                    "preflight estimate",
                    "records created",
                    "estimated remaining",
                    "Creating portable review",
                    "Consolidating",
                )
            ):
                self._update_generation_progress_message(text)

    def _cancel_generation(self):
        process = self._generation_process
        if process is None or process.state() == PROCESS_NOT_RUNNING:
            return
        self._generation_canceled = True
        self._update_generation_progress_message("Stopping the isolated worker…")
        process.terminate()
        QTimer.singleShot(
            3000,
            lambda: process.kill()
            if process.state() != PROCESS_NOT_RUNNING
            else None,
        )

    def _find_generation_output_folder(self):
        matches = re.findall(
            r"^OUTPUT_FOLDER:\s*(.+?)\s*$",
            self._generation_output,
            flags=re.MULTILINE,
        )
        if matches:
            candidate = Path(matches[-1].strip().strip('"'))
            if candidate.is_dir():
                return candidate
        parent = self._generation_output_parent
        if parent and parent.is_dir():
            candidates = [
                path
                for path in parent.glob("Fake_Farm_Data_*")
                if path.is_dir() and str(path) not in self._generation_existing_folders
            ]
            if candidates:
                return max(candidates, key=lambda path: path.stat().st_mtime_ns)
        return None

    @staticmethod
    def _mark_incomplete(folder, reason):
        if folder is None:
            return
        manifest_path = folder / "run_manifest.json"
        try:
            payload = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.is_file()
                else {}
            )
            payload["status"] = "incomplete"
            payload["incomplete_reason"] = str(reason)
            manifest_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    def _run_generation_with_progress(self, parameters):
        """Run in an isolated qgis_process worker so desktop QGIS remains safe."""

        if self._generation_running:
            QMessageBox.information(
                self,
                "Generation already running",
                "Wait for the current fake-data run to finish or cancel it.",
            )
            return
        try:
            worker_parameters = dict(parameters)
            worker_parameters["INPUT"] = self._snapshot_generation_input(
                parameters["INPUT"]
            )
            crop_payload = str(worker_parameters.get("CROP_ASSIGNMENTS_JSON", ""))
            if len(crop_payload) > 1024:
                crop_payload_path = Path(
                    QgsProcessingUtils.generateTempFilename(
                        "fake_farm_crop_assignments.json"
                    )
                )
                crop_payload_path.write_text(crop_payload, encoding="utf-8")
                worker_parameters["CROP_ASSIGNMENTS_JSON"] = f"@{crop_payload_path}"
            program = self._qgis_process_program()
            arguments = self._qgis_process_arguments(worker_parameters)
        except Exception as error:
            QMessageBox.critical(self, "Generation could not start", str(error))
            return

        progress = QProgressDialog(
            "Starting isolated QGIS worker…"
            + (
                f"\nEstimated runtime: {self._pending_runtime_estimate}"
                if self._pending_runtime_estimate
                else ""
            ),
            "Cancel",
            0,
            100,
            self,
        )
        progress.setWindowTitle("Creating Fake Farm Data")
        progress.setWindowModality(QT_WINDOW_MODAL)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        process = QProcess(self)
        process.setProcessChannelMode(PROCESS_MERGED_CHANNELS)

        self._generation_running = True
        self._generation_process = process
        self._generation_progress = progress
        self._generation_error = ""
        self._generation_messages = []
        self._generation_output = ""
        self._generation_output_parent = Path(str(parameters["OUTPUT_DIR"]))
        self._generation_existing_folders = {
            str(path)
            for path in self._generation_output_parent.glob("Fake_Farm_Data_*")
            if path.is_dir()
        }
        self._generation_input_path = worker_parameters["INPUT"]
        self._generation_canceled = False
        self._generation_started_at = time.monotonic()
        self._generation_last_progress_marker = -1
        process.readyReadStandardOutput.connect(self._read_generation_output)
        process.finished.connect(self._generation_process_finished)
        process.errorOccurred.connect(
            lambda error: setattr(
                self,
                "_generation_error",
                f"Worker process error: {error}",
            )
        )
        progress.canceled.connect(self._cancel_generation)
        self._set_generation_controls_enabled(False)
        progress.show()
        process.start(program, arguments)
        if not process.waitForStarted(5000):
            self._generation_error = process.errorString()
            self._generation_process_finished(-1, PROCESS_NORMAL_EXIT)

    def _generation_process_finished(self, exit_code, exit_status):
        process = self._generation_process
        if process is not None:
            self._read_generation_output()
        folder = self._find_generation_output_folder()
        canceled = self._generation_canceled
        successful = (
            not canceled
            and int(exit_code) == 0
            and exit_status == PROCESS_NORMAL_EXIT
            and folder is not None
        )
        elapsed_seconds = max(
            0.0,
            time.monotonic() - self._generation_started_at,
        ) if self._generation_started_at is not None else 0.0
        if canceled or not successful:
            self._mark_incomplete(
                folder,
                "user_canceled" if canceled else f"worker_exit_{exit_code}",
            )
        progress = self._generation_progress
        if progress is not None:
            if successful:
                progress.setValue(100)
            progress.close()
            progress.deleteLater()
        if process is not None:
            process.deleteLater()
        self._generation_running = False
        self._generation_process = None
        self._generation_progress = None
        self._generation_input_path = None
        self._generation_started_at = None
        self._set_generation_controls_enabled(True)
        if folder is not None:
            self.output_folder = folder
            self.open_output.setEnabled(folder.exists())
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        if successful:
            manifest_path = folder / "run_manifest.json"
            manifest = {}
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["desktop_elapsed_seconds"] = round(elapsed_seconds, 3)
                manifest["desktop_elapsed"] = format_duration(elapsed_seconds)
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                manifest = {}
            count_labels = {
                "soil_points": "soil-test points",
                "soil_surface_cells": "soil surface cells",
                "planter_center_points": "planter-center points",
                "row_unit_points": "planting row-unit points",
                "planting_surface_cells": "planting surface cells",
                "application_points": "application points",
                "yield_points": "yield points",
                "surface_cells": "application/yield surface cells",
            }
            created = [
                f"{int(value):,} {count_labels[key]}"
                for key, value in manifest.get("counts", {}).items()
                if key in count_labels and isinstance(value, (int, float)) and value > 0
            ]
            created_text = "\n".join(f"• {item}" for item in created) or "• Output files and review"
            review_path = folder / "fake_farm_data_review.html"
            message = QMessageBox(self)
            message.setWindowTitle("Fake data created")
            message.setText(
                f"Generation completed in {format_duration(elapsed_seconds)}.\n\n"
                f"Created:\n{created_text}\n\nSaved to:\n{folder}"
            )
            open_review = None
            if review_path.is_file():
                open_review = message.addButton(
                    "Open HTML Review", MESSAGE_ACTION_ROLE
                )
            open_folder = message.addButton("Open Output Folder", MESSAGE_ACTION_ROLE)
            message.addButton("Close", MESSAGE_REJECT_ROLE)
            message.exec()
            if open_review is not None and message.clickedButton() is open_review:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(review_path)))
            elif message.clickedButton() is open_folder:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif canceled:
            QMessageBox.information(
                self,
                "Generation canceled",
                "The isolated worker was stopped. Any partial run is marked incomplete.",
            )
        else:
            tail = "\n".join(
                line.strip()
                for line in self._generation_output.splitlines()[-20:]
                if line.strip()
            )
            QMessageBox.critical(
                self,
                "Generation failed",
                (self._generation_error or f"Worker exited with code {exit_code}.")
                + (f"\n\n{tail[-1800:]}" if tail else ""),
            )

    def _preflight_estimate(
        self,
        layer,
        enabled,
        operations_json,
        soil_settings,
        planting_settings,
        yield_settings,
    ):
        years = parse_years(self._years_text())
        features = (
            list(layer.selectedFeatures())
            if layer.selectedFeatureCount() > 0
            else list(layer.getFeatures())
        )
        if not features:
            raise ValueError("No field features were supplied")
        if len(features) > 20:
            raise ValueError(f"Selected {len(features)} fields; the v1 limit is 20 fields")
        if not layer.crs().isValid():
            raise ValueError("Field-boundary layer has a missing or invalid CRS")
        calculator = QgsDistanceArea()
        calculator.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        calculator.setEllipsoid("WGS84")
        area_m2 = sum(
            abs(calculator.measureArea(feature.geometry()))
            for feature in features
            if feature.hasGeometry() and not feature.geometry().isEmpty()
        )
        acres = area_m2 / 4046.8564224
        if area_m2 <= 0:
            raise ValueError("Selected field polygons have no measurable area")
        if acres > 5000.0 + 0.001:
            raise ValueError(
                f"Selected fields total {acres:,.1f} acres; the v1 limit is 5,000 acres"
            )
        operations = (
            normalize_application_operations(operations_json, years)
            if enabled["applications"]
            else []
        )
        soil_years = (
            resolve_soil_schedule(
                years,
                self.soil_interval.value(),
                self.soil_first_year.currentData(),
                self.soil_final_year.currentData(),
            )
            if enabled["soil"]
            else []
        )
        estimates = estimate_complete_records(
            area_m2,
            years,
            enabled,
            self.soil_interval.value(),
            self.unit_system.currentIndex(),
            operations,
            soil_settings,
            planting_settings,
            yield_settings,
            soil_years,
        )
        return years, operations, estimates, len(features), acres, soil_years

    def review_generation(self):
        """Validate the configuration and show the required preflight review page."""

        self.run_generation(review_only=True)

    def run_generation(self, review_only=False):
        output = Path(self.output_directory.text().strip())
        if not output.is_dir():
            QMessageBox.warning(self, "Missing output", "Select an existing parent output directory.")
            return
        formats = [index for index, checkbox in enumerate(self.format_checks) if checkbox.isChecked()]
        application_rows = self._application_rows()
        application_json = json.dumps(application_rows)
        soil_settings_raw = self._soil_settings()
        planting_settings_raw = self._planting_settings()
        yield_settings_raw = self._yield_settings()
        enabled_by_type = {
            "soil": self.create_soil.isChecked(),
            "planting": self.create_planting.isChecked(),
            "applications": self.create_applications.isChecked(),
            "yield": self.create_yield.isChecked(),
        }
        try:
            layer = self._combined_boundary_layer()
            timezone_label = normalize_timezone_label(self._timezone_text())
            soil_settings = (
                normalize_soil_settings(soil_settings_raw, self.unit_system.currentIndex())
                if enabled_by_type["soil"]
                else default_soil_settings(self.unit_system.currentIndex())
            )
            planting_settings = (
                normalize_planting_settings(
                    planting_settings_raw, self.unit_system.currentIndex()
                )
                if enabled_by_type["planting"]
                else default_planting_settings(self.unit_system.currentIndex())
            )
            yield_settings = (
                normalize_yield_settings(yield_settings_raw, self.unit_system.currentIndex())
                if enabled_by_type["yield"]
                else default_yield_settings(self.unit_system.currentIndex())
            )
            years, normalized_operations, estimates, field_count, acres, soil_years = (
                self._preflight_estimate(
                    layer,
                    enabled_by_type,
                    application_json,
                    soil_settings,
                    planting_settings,
                    yield_settings,
                )
            )
        except (TypeError, ValueError) as error:
            QMessageBox.warning(self, "Invalid complete-run settings", str(error))
            return
        crop_assignments_json = ""
        if enabled_by_type["planting"] or enabled_by_type["yield"]:
            try:
                crop_assignments_json = self._crop_assignments_json(require_complete=True)
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                QMessageBox.warning(self, "Crop lookup required", str(error))
                self.tabs.setCurrentIndex(1)
                return
        parameters = {
            "INPUT": layer,
            "FIELD_ID_FIELD": "field_id",
            "FIELD_NAME_FIELD": "field_name",
            "FARM_NAME_FIELD": "farm_name",
            "GROWER_NAME_FIELD": "grower_name",
            "UNIT_SYSTEM": self.unit_system.currentIndex(),
            "YEARS": self._years_text(),
            "TIMEZONE": timezone_label,
            "CREATE_SOIL": self.create_soil.isChecked(),
            "SOIL_SETTINGS_JSON": json.dumps(soil_settings_raw),
            "CREATE_PLANTING": self.create_planting.isChecked(),
            "PLANTING_SETTINGS_JSON": json.dumps(planting_settings_raw),
            "CREATE_APPLICATIONS": self.create_applications.isChecked(),
            "APPLICATION_OPERATIONS_JSON": application_json,
            "CREATE_YIELD": self.create_yield.isChecked(),
            "YIELD_SETTINGS_JSON": json.dumps(yield_settings_raw),
            "SOIL_INTERVAL": self.soil_interval.value(),
            "SOIL_FIRST_YEAR": str(soil_years[0]) if soil_years else "",
            "SOIL_FINAL_YEAR": str(soil_years[-1]) if soil_years else "",
            "CROP_LOOKUP_MODE": 1,
            "CROP_PROFILE": self.manual_crop.currentIndex(),
            "LOCAL_CDL_PATH": "",
            "CDL_CACHE_DIRECTORY": "",
            "CROP_OVERRIDES_JSON": "",
            "CROP_ASSIGNMENTS_JSON": crop_assignments_json,
            "OUTPUT_FORMATS": formats,
            "REVIEW_MAX_FEATURES": self.review_max_features.value(),
            "RANDOM_SEED": self.seed.value(),
            "OUTPUT_DIR": str(output),
        }
        enabled = [key for key in ("CREATE_SOIL", "CREATE_PLANTING", "CREATE_APPLICATIONS", "CREATE_YIELD") if parameters[key]]
        if not enabled:
            QMessageBox.warning(self, "No data selected", "Select at least one data type.")
            return
        operation_count = len(normalized_operations)
        area_text = (
            f"{acres / 2.4710538147:,.1f} hectares"
            if self.unit_system.currentIndex() == 1
            else f"{acres:,.1f} acres"
        )
        estimate_text = (
            f"Preflight estimate: {estimates['total_points']:,} points + "
            f"{estimates['total_surface_cells']:,} surface cells = "
            f"{estimates['total_records']:,} total records."
        )
        self.summary.setText(
            f"{field_count} field(s), {area_text}, {len(years)} year(s). {estimate_text} "
            "Every successful run creates the portable comparison review."
        )
        used_selection = any(
            selected_layer.selectedFeatureCount() > 0
            for selected_layer in self._selected_boundary_layers()
        )
        output_format_names = [OUTPUT_FORMAT_OPTIONS[index] for index in formats]
        runtime_estimate = runtime_estimate_text(
            estimates,
            output_format_names,
            self.review_max_features.value(),
        )
        self._pending_runtime_estimate = runtime_estimate
        crop_required = enabled_by_type["planting"] or enabled_by_type["yield"]
        automatic_crop = crop_required
        if not crop_required:
            crop_review_status = "Not required for the selected data types"
            network_requirement = "None"
        elif automatic_crop:
            reviewed_count = field_count * len(years)
            inferred_count = sum(
                1
                for assignment in self._crop_suggestions.values()
                if assignment.crop_source == "rotation_inference"
            )
            crop_review_status = (
                f"{reviewed_count:,} field-year assignments from USDA CDL; "
                f"{inferred_count:,} rotation estimate(s)"
            )
            network_requirement = "USDA CroplandCROS API is contacted only when Pull Crops is selected"
        review_text = build_preflight_review_text(
            field_count=field_count,
            used_selection=used_selection,
            area_text=area_text,
            years=years,
            enabled=enabled_by_type,
            estimates=estimates,
            output_formats=output_format_names,
            operation_count=operation_count,
            crop_mode="USDA CDL API" if crop_required else "Not required",
            crop_review_status=crop_review_status,
            network_requirement=network_requirement,
            output_directory=output,
            timezone_label=timezone_label,
            review_max_features=self.review_max_features.value(),
            runtime_estimate=runtime_estimate,
        )
        self.preflight_review.setPlainText(review_text)
        self.execute_button.setEnabled(True)
        self.tabs.setCurrentIndex(self.tabs.count() - 1)
        if review_only:
            return
        answer = QMessageBox.question(
            self,
            "Run fake-data generation?",
            f"Create {len(enabled)} data type(s) for {parameters['YEARS']}?\n"
            f"Fields: {field_count} ({area_text})\n"
            f"Application operations after year expansion: {operation_count}\n"
            f"Estimated points: {estimates['total_points']:,}\n"
            f"Estimated surface cells: {estimates['total_surface_cells']:,}\n"
            f"Estimated total records: {estimates['total_records']:,}\n\n"
            f"Estimated runtime: {runtime_estimate}\n\n"
            "This may take a while. QGIS must remain open until processing finishes.",
        )
        if answer != MESSAGE_YES:
            return
        self._run_generation_with_progress(parameters)

    def reject(self):
        if self._generation_running:
            QMessageBox.information(
                self,
                "Generation in progress",
                "Cancel the running task and wait for it to stop before closing this window.",
            )
            return
        super().reject()

    def shutdown(self):
        """Stop an isolated worker during plugin unload or QGIS shutdown."""

        process = self._generation_process
        if process is not None and process.state() != PROCESS_NOT_RUNNING:
            self._generation_canceled = True
            try:
                process.finished.disconnect(self._generation_process_finished)
                process.readyReadStandardOutput.disconnect(
                    self._read_generation_output
                )
            except (TypeError, RuntimeError):
                pass
            process.terminate()
            if not process.waitForFinished(3000):
                process.kill()
                process.waitForFinished(1000)
        if self._generation_progress is not None:
            self._generation_progress.close()
        self._generation_running = False
        self._generation_process = None
        self._generation_progress = None
        super().reject()

    def closeEvent(self, event):
        if self._generation_running:
            event.ignore()
            QMessageBox.information(
                self,
                "Generation in progress",
                "Cancel the running task and wait for it to stop before closing this window.",
            )
            return
        super().closeEvent(event)
