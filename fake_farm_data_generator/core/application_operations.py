# SPDX-License-Identifier: GPL-3.0-or-later
"""Dependency-free validation for complete-run application operations."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime

from .generation import normalize_timezone_label


OPERATION_TYPES = [
    "Dry Fertilizer",
    "Liquid Fertilizer",
    "Lime",
    "Chemical Spraying",
    "Manure",
    "Seeding or Broadcast Seeding",
]
RATE_MODES = ["Flat Rate", "Variable Rate"]
DIRECTION_MODES = ["Automatic", "Manual"]
VARIABILITY_LEVELS = ["Low", "Medium", "High"]

_SAFE_OPERATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def default_application_operation(year="all", sequence=1):
    """Return a serializable baseline operation used by the dialog and toolbox."""

    return {
        "enabled": True,
        "year": year,
        "operation_id": f"APP_{sequence:03d}",
        "operation_type": "Dry Fertilizer",
        "product_name": "Fake Product",
        "rate_mode": "Flat Rate",
        "target_rate": 150.0,
        "min_rate": 120.0,
        "max_rate": 180.0,
        "rate_unit": "lb/acre",
        "base_date": "04-15",
        "date_window": 14,
        "timezone": "",
        "equipment_width": 60.0,
        "nominal_speed": 10.0,
        "logging_interval": 1.0,
        "headland_passes": 2,
        "direction_mode": "Automatic",
        "manual_bearing": 0.0,
        "variability_level": "Medium",
        "create_surface": True,
        "surface_grid_size": 30.0,
    }


def _enum_value(value, options, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be one of: {', '.join(options)}")
    if isinstance(value, int):
        if 0 <= value < len(options):
            return options[value]
    else:
        text = str(value).strip().casefold()
        for option in options:
            if text == option.casefold():
                return option
    raise ValueError(f"{label} must be one of: {', '.join(options)}")


def _number(operation, key, default, minimum=None, maximum=None):
    try:
        value = float(operation.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be numeric") from error
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} must be no more than {maximum}")
    return value


def _integer(operation, key, default, minimum=None, maximum=None):
    value = _number(operation, key, default, minimum, maximum)
    if not value.is_integer():
        raise ValueError(f"{key} must be a whole number")
    return int(value)


def _boolean(value, label):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "yes", "1", "on"}:
        return True
    if text in {"false", "no", "0", "off"}:
        return False
    raise ValueError(f"{label} must be true or false")


def _target_years(value, selected_years):
    if value is None or str(value).strip().casefold() in {"", "all", "*"}:
        return list(selected_years)
    try:
        year = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("year must be a selected year or 'all'") from error
    if year not in selected_years:
        raise ValueError(f"year {year} is not one of the selected crop years")
    return [year]


def _validate_date(value):
    text = str(value).strip()
    try:
        datetime.strptime(f"2000-{text}", "%Y-%m-%d")
    except ValueError as error:
        raise ValueError("base_date must use MM-DD") from error
    return text


def normalize_application_operations(raw_json, selected_years):
    """Parse, expand, and validate complete-run application operations.

    ``year`` may be a selected integer year or ``"all"``. Disabled rows are
    ignored. Blank JSON retains the historical one-baseline-operation-per-year
    behavior used by Processing models that predate this parameter.
    """

    years = [int(year) for year in selected_years]
    if not years:
        raise ValueError("At least one crop year is required")
    if raw_json is None or str(raw_json).strip() == "":
        source_operations = [
            default_application_operation(year, sequence)
            for sequence, year in enumerate(years, start=1)
        ]
        for operation, year in zip(source_operations, years):
            operation["operation_id"] = f"APP_{year}_001"
    else:
        try:
            source_operations = json.loads(str(raw_json))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Application operations JSON is invalid at line {error.lineno}, column {error.colno}"
            ) from error
        if not isinstance(source_operations, list):
            raise ValueError("Application operations JSON must be a list")

    normalized = []
    seen = set()
    for row_index, source in enumerate(source_operations, start=1):
        if not isinstance(source, dict):
            raise ValueError(f"Application operation row {row_index} must be an object")
        try:
            if not _boolean(source.get("enabled", True), "enabled"):
                continue
            defaults = default_application_operation()
            operation_id = str(source.get("operation_id", defaults["operation_id"])).strip()
            if not _SAFE_OPERATION_ID.fullmatch(operation_id):
                raise ValueError(
                    "operation_id must be 1-64 characters using letters, numbers, hyphens, or underscores"
                )
            product_name = str(source.get("product_name", defaults["product_name"])).strip()
            rate_unit = str(source.get("rate_unit", defaults["rate_unit"])).strip()
            if not product_name:
                raise ValueError("product_name is required")
            if not rate_unit:
                raise ValueError("rate_unit is required")
            minimum_rate = _number(
                source, "min_rate", source.get("minimum_rate", defaults["min_rate"]), 0, 1_000_000
            )
            target_rate = _number(source, "target_rate", defaults["target_rate"], 0, 1_000_000)
            maximum_rate = _number(
                source, "max_rate", source.get("maximum_rate", defaults["max_rate"]), 0, 1_000_000
            )
            if not minimum_rate <= target_rate <= maximum_rate:
                raise ValueError("rates must satisfy min_rate <= target_rate <= max_rate")
            equipment_width = _number(
                source, "equipment_width", defaults["equipment_width"], 1, 300
            )
            if "headland_passes" in source:
                headland_passes = _integer(
                    source, "headland_passes", defaults["headland_passes"], 0, 20
                )
            elif "headland_width" in source:
                legacy_width = _number(source, "headland_width", 0, 0, 5000)
                headland_passes = min(
                    20, int(math.ceil(legacy_width / equipment_width))
                )
            else:
                headland_passes = defaults["headland_passes"]
            normalized_base = {
                "enabled": True,
                "operation_id": operation_id,
                "operation_type": _enum_value(
                    source.get("operation_type", defaults["operation_type"]),
                    OPERATION_TYPES,
                    "operation_type",
                ),
                "product_name": product_name,
                "rate_mode": _enum_value(
                    source.get("rate_mode", defaults["rate_mode"]), RATE_MODES, "rate_mode"
                ),
                "target_rate": target_rate,
                "min_rate": minimum_rate,
                "max_rate": maximum_rate,
                "rate_unit": rate_unit,
                "base_date": _validate_date(source.get("base_date", defaults["base_date"])),
                "date_window": _integer(source, "date_window", defaults["date_window"], 0, 90),
                "timezone": normalize_timezone_label(
                    source.get("timezone", defaults["timezone"])
                ),
                "equipment_width": equipment_width,
                "nominal_speed": _number(
                    source, "nominal_speed", defaults["nominal_speed"], 0.1, 60
                ),
                "logging_interval": _number(
                    source, "logging_interval", defaults["logging_interval"], 0.1, 60
                ),
                "headland_passes": headland_passes,
                "direction_mode": _enum_value(
                    source.get("direction_mode", defaults["direction_mode"]),
                    DIRECTION_MODES,
                    "direction_mode",
                ),
                "manual_bearing": _number(
                    source, "manual_bearing", defaults["manual_bearing"], 0, 359.999
                ),
                "variability_level": _enum_value(
                    source.get("variability_level", defaults["variability_level"]),
                    VARIABILITY_LEVELS,
                    "variability_level",
                ),
                "create_surface": _boolean(
                    source.get("create_surface", defaults["create_surface"]), "create_surface"
                ),
                "surface_grid_size": _number(
                    source, "surface_grid_size", defaults["surface_grid_size"], 5, 1000
                ),
            }
            for year in _target_years(source.get("year", defaults["year"]), years):
                key = (year, operation_id.casefold())
                if key in seen:
                    raise ValueError(
                        f"operation_id '{operation_id}' is duplicated for year {year}"
                    )
                seen.add(key)
                normalized.append({**normalized_base, "year": year})
        except ValueError as error:
            raise ValueError(f"Application operation row {row_index}: {error}") from error

    if not normalized:
        raise ValueError("At least one enabled application operation is required")
    return sorted(normalized, key=lambda item: (item["year"], item["operation_id"].casefold()))


def operation_to_processing_parameters(operation):
    """Map a normalized operation to the individual algorithm parameter names."""

    return {
        "CROP_YEAR": operation["year"],
        "OPERATION_ID": operation["operation_id"],
        "OPERATION_TYPE": OPERATION_TYPES.index(operation["operation_type"]),
        "PRODUCT_NAME": operation["product_name"],
        "RATE_MODE": RATE_MODES.index(operation["rate_mode"]),
        "TARGET_RATE": operation["target_rate"],
        "MIN_RATE": operation["min_rate"],
        "MAX_RATE": operation["max_rate"],
        "RATE_UNIT": operation["rate_unit"],
        "EQUIPMENT_WIDTH": operation["equipment_width"],
        "NOMINAL_SPEED": operation["nominal_speed"],
        "LOGGING_INTERVAL": operation["logging_interval"],
        "HEADLAND_PASSES": operation["headland_passes"],
        "DIRECTION_MODE": DIRECTION_MODES.index(operation["direction_mode"]),
        "MANUAL_BEARING": operation["manual_bearing"],
        "APPLICATION_MONTH_DAY": operation["base_date"],
        "DATE_WINDOW": operation["date_window"],
        "TIMEZONE": operation["timezone"],
        "VARIABILITY_LEVEL": VARIABILITY_LEVELS.index(operation["variability_level"]),
        "CREATE_SURFACE": operation["create_surface"],
        "SURFACE_GRID_SIZE": operation["surface_grid_size"],
    }
