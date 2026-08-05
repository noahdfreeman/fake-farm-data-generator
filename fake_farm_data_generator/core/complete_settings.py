# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated soil, planting, and yield settings for complete runs."""

from __future__ import annotations

import json
import math
from datetime import datetime

from .units import unit_system


SOIL_PLACEMENTS = ["Regular Grid", "Random"]
LEVELS = ["Low", "Medium", "High"]
SOIL_UNITS = ["ppm", "lb/acre"]
INTERPOLATION_METHODS = ["IDW", "Ordinary Kriging"]
KRIGING_MODELS = ["Spherical", "Exponential", "Gaussian"]
PLANTING_POINT_OUTPUTS = ["Planter Center", "Row Units", "Both"]
DIRECTION_MODES = ["Automatic", "Manual"]
PLANTING_SURFACE_ATTRIBUTES = [
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


_IMPERIAL_PLANTING_CROP_PROFILES = {
    "Corn": (26000.0, 32000.0, 38000.0, 2.0, "05-01"),
    "Soybeans": (100000.0, 140000.0, 180000.0, 1.5, "05-10"),
    "Wheat": (1000000.0, 1500000.0, 2000000.0, 1.25, "10-05"),
    "Cotton": (30000.0, 42000.0, 55000.0, 1.0, "05-10"),
    "Grain sorghum": (50000.0, 70000.0, 90000.0, 1.5, "05-15"),
    "Barley": (750000.0, 1100000.0, 1500000.0, 1.25, "04-10"),
    "Oats": (750000.0, 1100000.0, 1500000.0, 1.25, "04-01"),
    "Canola": (350000.0, 500000.0, 650000.0, 0.75, "04-15"),
    "Dry beans": (70000.0, 95000.0, 120000.0, 1.5, "05-20"),
    "Sunflowers": (14000.0, 22000.0, 30000.0, 1.5, "05-10"),
    "Alfalfa": (6500000.0, 9000000.0, 12000000.0, 0.5, "04-15"),
    "Other Crop": (26000.0, 32000.0, 38000.0, 1.5, "05-01"),
}


def planting_crop_profiles(unit_system_value=0):
    """Return fake crop-specific planting defaults in the selected units."""

    metric = unit_system(unit_system_value).metric
    population_factor = 2.4710538147 if metric else 1.0
    depth_factor = 2.54 if metric else 1.0
    return {
        crop: {
            "min_population": minimum * population_factor,
            "target_population": target * population_factor,
            "max_population": maximum * population_factor,
            "seed_depth": depth * depth_factor,
            "planting_date": planting_date,
        }
        for crop, (minimum, target, maximum, depth, planting_date) in
        _IMPERIAL_PLANTING_CROP_PROFILES.items()
    }


def default_soil_settings(unit_system_value=0):
    metric = unit_system(unit_system_value).metric
    return {
        "placement": "Regular Grid",
        "sample_density": 1.011714 if metric else 2.5,
        "boundary_setback": 45.72 if metric else 150.0,
        "grid_rotation": 0.0,
        "grid_offset_x": 0.0,
        "grid_offset_y": 0.0,
        "sample_depth": "0-20 cm" if metric else "0-8 inches",
        "lab_name": "Test Lab",
        "fertility_level": "Medium",
        "variability_level": "Medium",
        "p_unit": "ppm",
        "k_unit": "ppm",
        "sample_date": "11-10",
        "date_window": 14,
        "unattributed": False,
        "create_surface": True,
        "surface_grid_size": 9.144 if metric else 30.0,
        "interpolation_method": "Ordinary Kriging",
        "idw_power": 2.0,
        "max_neighbors": 12,
        "kriging_model": "Spherical",
        "kriging_range": 0.0,
        "kriging_nugget": 0.0,
    }


def default_planting_settings(unit_system_value=0):
    metric = unit_system(unit_system_value).metric
    profiles = planting_crop_profiles(unit_system_value)
    corn = profiles["Corn"]
    return {
        "point_output": "Planter Center",
        "planter_width": 12.192 if metric else 40.0,
        "row_units": 16,
        "row_spacing": 76.2 if metric else 30.0,
        "target_population": corn["target_population"],
        "min_population": corn["min_population"],
        "max_population": corn["max_population"],
        "seed_depth": corn["seed_depth"],
        "nominal_speed": 8.04672 if metric else 5.0,
        "logging_interval": 1.0,
        "headland_passes": 2,
        "direction_mode": "Automatic",
        "manual_bearing": 0.0,
        "planting_date": corn["planting_date"],
        "date_window": 14,
        "variability_level": "Medium",
        "create_surface": True,
        "surface_grid_size": 9.144 if metric else 30.0,
        "surface_attributes": list(PLANTING_SURFACE_ATTRIBUTES),
        "crop_profiles": profiles,
    }


def default_yield_settings(unit_system_value=0):
    metric = unit_system(unit_system_value).metric
    return {
        "swath_width": 9.144 if metric else 30.0,
        "nominal_speed": 6.437376 if metric else 4.0,
        "logging_interval": 1.0,
        # Three default combine passes cover the same depth as two 40-foot
        # planter passes when using the default 30-foot header.
        "headland_passes": 3,
        "headland_penalty": 10.0,
        "direction_mode": "Automatic",
        "manual_bearing": 0.0,
        "harvest_date": "10-15",
        "date_window": 14,
        "variability_level": "Medium",
        "create_surface": True,
        "surface_grid_size": 9.144 if metric else 30.0,
        "profile_overrides": {},
    }


def resolve_soil_schedule(years, interval, first_year=None, final_year=None):
    """Resolve the complete-run soil sampling schedule from visible controls."""

    selected = sorted({int(year) for year in years})
    if not selected:
        raise ValueError("Select at least one complete-run year")
    try:
        interval_value = int(interval)
    except (TypeError, ValueError) as error:
        raise ValueError("Soil sampling interval must be a whole number") from error
    if not 1 <= interval_value <= 25:
        raise ValueError("Soil sampling interval must be between 1 and 25 years")

    def optional_year(value, fallback, label):
        text = str(value if value is not None else "").strip()
        if not text:
            return fallback
        try:
            result = int(text)
        except ValueError as error:
            raise ValueError(f"{label} must be a whole year") from error
        if not 1900 <= result <= 2100:
            raise ValueError(f"{label} must be between 1900 and 2100")
        return result

    first = optional_year(first_year, selected[0], "First soil sampling year")
    final = optional_year(final_year, selected[-1], "Final soil sampling year")
    if first < selected[0] or first > selected[-1]:
        raise ValueError("First soil sampling year must fall within the complete-run years")
    if final < selected[0] or final > selected[-1]:
        raise ValueError("Final soil sampling year must fall within the complete-run years")
    if final < first:
        raise ValueError("Final soil sampling year cannot precede the first sampling year")
    schedule = list(range(first, final + 1, interval_value))
    if len(schedule) > 10:
        raise ValueError("A complete run may create soil tests for no more than 10 years")
    return schedule


def _object(raw, label):
    if raw is None or str(raw).strip() == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"{label} JSON is invalid at line {error.lineno}, column {error.colno}"
        ) from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} JSON must be an object")
    return value


def _enum(value, options, label):
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(options):
        return options[value]
    text = str(value).strip().casefold()
    aliases = {"kg/ha": "lb/acre"}
    text = aliases.get(text, text)
    for option in options:
        if text == option.casefold():
            return option
    raise ValueError(f"{label} must be one of: {', '.join(options)}")


def _number(source, key, default, minimum, maximum):
    try:
        value = float(source.get(key, default))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be numeric") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _integer(source, key, default, minimum, maximum):
    value = _number(source, key, default, minimum, maximum)
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


def _date(value, label):
    text = str(value).strip()
    try:
        datetime.strptime(f"2000-{text}", "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"{label} must use MM-DD") from error
    return text


def _text(value, label):
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def normalize_soil_settings(raw, unit_system_value=0):
    source = _object(raw, "Soil settings")
    defaults = default_soil_settings(unit_system_value)
    result = {
        "placement": _enum(source.get("placement", defaults["placement"]), SOIL_PLACEMENTS, "placement"),
        "sample_density": _number(source, "sample_density", defaults["sample_density"], 0.25, 50),
        "boundary_setback": _number(source, "boundary_setback", defaults["boundary_setback"], 0, 5000),
        "grid_rotation": _number(source, "grid_rotation", defaults["grid_rotation"], -180, 180),
        "grid_offset_x": _number(source, "grid_offset_x", defaults["grid_offset_x"], -100, 100),
        "grid_offset_y": _number(source, "grid_offset_y", defaults["grid_offset_y"], -100, 100),
        "sample_depth": _text(source.get("sample_depth", defaults["sample_depth"]), "sample_depth"),
        "lab_name": _text(source.get("lab_name", defaults["lab_name"]), "lab_name"),
        "fertility_level": _enum(source.get("fertility_level", defaults["fertility_level"]), LEVELS, "fertility_level"),
        "variability_level": _enum(source.get("variability_level", defaults["variability_level"]), LEVELS, "variability_level"),
        "p_unit": _enum(source.get("p_unit", defaults["p_unit"]), SOIL_UNITS, "p_unit"),
        "k_unit": _enum(source.get("k_unit", defaults["k_unit"]), SOIL_UNITS, "k_unit"),
        "sample_date": _date(source.get("sample_date", defaults["sample_date"]), "sample_date"),
        "date_window": _integer(source, "date_window", defaults["date_window"], 0, 90),
        "unattributed": _boolean(source.get("unattributed", defaults["unattributed"]), "unattributed"),
        "create_surface": _boolean(source.get("create_surface", defaults["create_surface"]), "create_surface"),
        "surface_grid_size": _number(source, "surface_grid_size", defaults["surface_grid_size"], 5, 1000),
        "interpolation_method": _enum(source.get("interpolation_method", defaults["interpolation_method"]), INTERPOLATION_METHODS, "interpolation_method"),
        "idw_power": _number(source, "idw_power", defaults["idw_power"], 0.1, 10),
        "max_neighbors": _integer(source, "max_neighbors", defaults["max_neighbors"], 1, 100),
        "kriging_model": _enum(source.get("kriging_model", defaults["kriging_model"]), KRIGING_MODELS, "kriging_model"),
        "kriging_range": _number(source, "kriging_range", defaults["kriging_range"], 0, 100000),
        "kriging_nugget": _number(source, "kriging_nugget", defaults["kriging_nugget"], 0, 1),
    }
    if result["unattributed"]:
        result["create_surface"] = False
    return result


def normalize_planting_settings(raw, unit_system_value=0):
    source = _object(raw, "Planting settings")
    defaults = default_planting_settings(unit_system_value)
    attributes = source.get("surface_attributes", defaults["surface_attributes"])
    if not isinstance(attributes, list):
        raise ValueError("surface_attributes must be a list")
    normalized_attributes = []
    for value in attributes:
        option = _enum(value, PLANTING_SURFACE_ATTRIBUTES, "surface attribute")
        if option not in normalized_attributes:
            normalized_attributes.append(option)
    raw_profiles = source.get("crop_profiles", defaults["crop_profiles"])
    if not isinstance(raw_profiles, dict):
        raise ValueError("crop_profiles must be an object keyed by crop name")
    crop_profiles = {}
    for crop_name, default_profile in defaults["crop_profiles"].items():
        raw_profile = raw_profiles.get(crop_name, default_profile)
        if not isinstance(raw_profile, dict):
            raise ValueError(f"Planting crop profile for {crop_name} must be an object")
        profile = {
            "min_population": _number(raw_profile, "min_population", default_profile["min_population"], 0, 50_000_000),
            "target_population": _number(raw_profile, "target_population", default_profile["target_population"], 100, 50_000_000),
            "max_population": _number(raw_profile, "max_population", default_profile["max_population"], 1, 50_000_000),
            "seed_depth": _number(
                raw_profile,
                "seed_depth",
                default_profile["seed_depth"],
                0.1,
                25.4 if unit_system(unit_system_value).metric else 10,
            ),
            "planting_date": _date(
                raw_profile.get("planting_date", default_profile["planting_date"]),
                f"{crop_name} planting_date",
            ),
        }
        if not profile["min_population"] <= profile["target_population"] <= profile["max_population"]:
            raise ValueError(
                f"{crop_name} population values must satisfy minimum <= target <= maximum"
            )
        crop_profiles[crop_name] = profile
    planter_width = _number(source, "planter_width", defaults["planter_width"], 1, 200)
    if "headland_passes" in source:
        headland_passes = _integer(source, "headland_passes", defaults["headland_passes"], 0, 20)
    elif "headland_width" in source:
        legacy_width = _number(source, "headland_width", 0, 0, 5000)
        headland_passes = min(20, int(math.ceil(legacy_width / planter_width)))
    else:
        headland_passes = defaults["headland_passes"]
    result = {
        "point_output": _enum(source.get("point_output", defaults["point_output"]), PLANTING_POINT_OUTPUTS, "point_output"),
        "planter_width": planter_width,
        "row_units": _integer(source, "row_units", defaults["row_units"], 1, 120),
        "row_spacing": _number(source, "row_spacing", defaults["row_spacing"], 5, 120),
        "target_population": _number(source, "target_population", defaults["target_population"], 100, 5000000),
        "min_population": _number(source, "min_population", defaults["min_population"], 0, 5000000),
        "max_population": _number(source, "max_population", defaults["max_population"], 1, 5000000),
        "seed_depth": _number(
            source,
            "seed_depth",
            defaults["seed_depth"],
            0.1,
            25.4 if unit_system(unit_system_value).metric else 10,
        ),
        "nominal_speed": _number(source, "nominal_speed", defaults["nominal_speed"], 0.1, 60),
        "logging_interval": _number(source, "logging_interval", defaults["logging_interval"], 0.1, 60),
        "headland_passes": headland_passes,
        "direction_mode": _enum(source.get("direction_mode", defaults["direction_mode"]), DIRECTION_MODES, "direction_mode"),
        "manual_bearing": _number(source, "manual_bearing", defaults["manual_bearing"], 0, 359.999),
        "planting_date": _date(source.get("planting_date", defaults["planting_date"]), "planting_date"),
        "date_window": _integer(source, "date_window", defaults["date_window"], 0, 90),
        "variability_level": _enum(source.get("variability_level", defaults["variability_level"]), LEVELS, "variability_level"),
        "create_surface": _boolean(source.get("create_surface", defaults["create_surface"]), "create_surface"),
        "surface_grid_size": _number(source, "surface_grid_size", defaults["surface_grid_size"], 5, 1000),
        "surface_attributes": normalized_attributes,
        "crop_profiles": crop_profiles,
    }
    if not result["min_population"] <= result["target_population"] <= result["max_population"]:
        raise ValueError("population values must satisfy min_population <= target_population <= max_population")
    if result["create_surface"] and not result["surface_attributes"]:
        raise ValueError("Select at least one planting surface attribute")
    return result


def normalize_yield_settings(raw, unit_system_value=0):
    source = _object(raw, "Yield settings")
    defaults = default_yield_settings(unit_system_value)
    raw_overrides = source.get("profile_overrides", defaults["profile_overrides"])
    if not isinstance(raw_overrides, dict):
        raise ValueError("profile_overrides must be an object keyed by crop name")
    profile_overrides = {}
    for crop_name, raw_profile in raw_overrides.items():
        name = str(crop_name).strip()
        if not name:
            raise ValueError("Yield profile override crop name cannot be blank")
        if not isinstance(raw_profile, dict):
            raise ValueError(f"Yield profile override for {name} must be an object")
        values = {
            "min_yield": _number(raw_profile, "min_yield", 0, 0, 5_000_000),
            "max_yield": _number(raw_profile, "max_yield", 1, 0, 5_000_000),
            "min_moisture": _number(raw_profile, "min_moisture", 0, 0, 99),
            "max_moisture": _number(raw_profile, "max_moisture", 99, 0, 99),
            "standard_moisture": _number(
                raw_profile, "standard_moisture", 15, 0, 99
            ),
        }
        if values["min_yield"] > values["max_yield"]:
            raise ValueError(f"{name} min_yield cannot exceed max_yield")
        if not (
            values["min_moisture"]
            <= values["standard_moisture"]
            <= values["max_moisture"]
        ):
            raise ValueError(
                f"{name} moisture values must satisfy minimum <= standard <= maximum"
            )
        profile_overrides[name] = values

    swath_width = _number(source, "swath_width", defaults["swath_width"], 1, 100)
    if "headland_passes" in source:
        headland_passes = _integer(source, "headland_passes", defaults["headland_passes"], 0, 20)
    elif "headland_width" in source:
        legacy_width = _number(source, "headland_width", 0, 0, 5000)
        headland_passes = min(20, int(math.ceil(legacy_width / swath_width)))
    else:
        headland_passes = defaults["headland_passes"]
    return {
        "swath_width": swath_width,
        "nominal_speed": _number(source, "nominal_speed", defaults["nominal_speed"], 0.1, 60),
        "logging_interval": _number(source, "logging_interval", defaults["logging_interval"], 0.1, 60),
        "headland_passes": headland_passes,
        "headland_penalty": _number(source, "headland_penalty", defaults["headland_penalty"], 0, 75),
        "direction_mode": _enum(source.get("direction_mode", defaults["direction_mode"]), DIRECTION_MODES, "direction_mode"),
        "manual_bearing": _number(source, "manual_bearing", defaults["manual_bearing"], 0, 359.999),
        "harvest_date": _date(source.get("harvest_date", defaults["harvest_date"]), "harvest_date"),
        "date_window": _integer(source, "date_window", defaults["date_window"], 0, 90),
        "variability_level": _enum(source.get("variability_level", defaults["variability_level"]), LEVELS, "variability_level"),
        "create_surface": _boolean(source.get("create_surface", defaults["create_surface"]), "create_surface"),
        "surface_grid_size": _number(source, "surface_grid_size", defaults["surface_grid_size"], 5, 1000),
        "profile_overrides": profile_overrides,
    }


def soil_processing_parameters(settings):
    return {
        "PLACEMENT": SOIL_PLACEMENTS.index(settings["placement"]),
        "SAMPLE_DENSITY": settings["sample_density"],
        "BOUNDARY_SETBACK": settings["boundary_setback"],
        "GRID_ROTATION": settings["grid_rotation"],
        "GRID_OFFSET_X": settings["grid_offset_x"],
        "GRID_OFFSET_Y": settings["grid_offset_y"],
        "SAMPLE_DEPTH": settings["sample_depth"],
        "LAB_NAME": settings["lab_name"],
        "FERTILITY_LEVEL": LEVELS.index(settings["fertility_level"]),
        "VARIABILITY_LEVEL": LEVELS.index(settings["variability_level"]),
        "P_UNIT": SOIL_UNITS.index(settings["p_unit"]),
        "K_UNIT": SOIL_UNITS.index(settings["k_unit"]),
        "SAMPLE_MONTH_DAY": settings["sample_date"],
        "DATE_WINDOW": settings["date_window"],
        "CREATE_UNATTRIBUTED": settings["unattributed"],
        "CREATE_SURFACE": settings["create_surface"],
        "SURFACE_GRID_SIZE": settings["surface_grid_size"],
        "INTERPOLATION_METHOD": INTERPOLATION_METHODS.index(settings["interpolation_method"]),
        "IDW_POWER": settings["idw_power"],
        "MAX_NEIGHBORS": settings["max_neighbors"],
        "KRIGING_MODEL": KRIGING_MODELS.index(settings["kriging_model"]),
        "KRIGING_RANGE": settings["kriging_range"],
        "KRIGING_NUGGET": settings["kriging_nugget"],
    }


def planting_processing_parameters(settings):
    parameters = {
        "POINT_OUTPUT": PLANTING_POINT_OUTPUTS.index(settings["point_output"]),
        "PLANTER_WIDTH": settings["planter_width"],
        "ROW_UNITS": settings["row_units"],
        "ROW_SPACING": settings["row_spacing"],
        "TARGET_POPULATION": settings["target_population"],
        "MIN_POPULATION": settings["min_population"],
        "MAX_POPULATION": settings["max_population"],
        "SEED_DEPTH": settings["seed_depth"],
        "NOMINAL_SPEED": settings["nominal_speed"],
        "LOGGING_INTERVAL": settings["logging_interval"],
        "HEADLAND_PASSES": settings["headland_passes"],
        "DIRECTION_MODE": DIRECTION_MODES.index(settings["direction_mode"]),
        "MANUAL_BEARING": settings["manual_bearing"],
        "PLANTING_MONTH_DAY": settings["planting_date"],
        "DATE_WINDOW": settings["date_window"],
        "VARIABILITY_LEVEL": LEVELS.index(settings["variability_level"]),
        "CREATE_SURFACE": settings["create_surface"],
        "SURFACE_GRID_SIZE": settings["surface_grid_size"],
    }
    if settings["surface_attributes"]:
        parameters["SURFACE_ATTRIBUTES"] = [
            PLANTING_SURFACE_ATTRIBUTES.index(value)
            for value in settings["surface_attributes"]
        ]
    return parameters


def yield_processing_parameters(settings):
    return {
        "SWATH_WIDTH": settings["swath_width"],
        "NOMINAL_SPEED": settings["nominal_speed"],
        "LOGGING_INTERVAL": settings["logging_interval"],
        "HEADLAND_PASSES": settings["headland_passes"],
        "HEADLAND_PENALTY": settings["headland_penalty"],
        "DIRECTION_MODE": DIRECTION_MODES.index(settings["direction_mode"]),
        "MANUAL_BEARING": settings["manual_bearing"],
        "HARVEST_MONTH_DAY": settings["harvest_date"],
        "DATE_WINDOW": settings["date_window"],
        "VARIABILITY_LEVEL": LEVELS.index(settings["variability_level"]),
        "CREATE_SURFACE": settings["create_surface"],
        "SURFACE_GRID_SIZE": settings["surface_grid_size"],
    }
