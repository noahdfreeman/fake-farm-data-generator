# SPDX-License-Identifier: GPL-3.0-or-later
"""Fast complete-run record estimates using the generator preflight formulas."""

from __future__ import annotations

import math

from .units import unit_system
from .complete_settings import (
    default_planting_settings,
    default_soil_settings,
    default_yield_settings,
)


def _machine_points(area_m2, width_m, speed_mps, interval_seconds):
    spacing_m = max(0.01, speed_mps * interval_seconds)
    return max(1, int(math.ceil(area_m2 / max(0.01, width_m * spacing_m))))


def _surface_cells(area_m2, grid_size_m):
    return int(math.ceil(area_m2 / max(0.01, grid_size_m**2)))


def estimate_complete_records(
    total_area_m2,
    years,
    enabled,
    soil_interval,
    unit_system_value,
    application_operations,
    soil_settings=None,
    planting_settings=None,
    yield_settings=None,
    soil_years=None,
):
    """Estimate points and polygon-grid cells for the complete-run defaults."""

    area_m2 = max(0.0, float(total_area_m2))
    selected_years = sorted({int(year) for year in years})
    units = unit_system(unit_system_value)
    soil_settings = soil_settings or default_soil_settings(unit_system_value)
    planting_settings = planting_settings or default_planting_settings(unit_system_value)
    yield_settings = yield_settings or default_yield_settings(unit_system_value)
    estimates = {
        "soil_points": 0,
        "soil_surface_cells": 0,
        "planter_center_points": 0,
        "planting_row_unit_points": 0,
        "planting_surface_cells": 0,
        "application_points": 0,
        "application_surface_cells": 0,
        "yield_points": 0,
        "yield_surface_cells": 0,
    }
    if not selected_years or area_m2 <= 0:
        return {**estimates, "total_points": 0, "total_surface_cells": 0, "total_records": 0}

    if enabled.get("soil"):
        soil_year_count = (
            len(list(soil_years))
            if soil_years is not None
            else len(
                range(
                    selected_years[0],
                    selected_years[-1] + 1,
                    max(1, int(soil_interval)),
                )
            )
        )
        area_display = units.area_from_square_meters(area_m2)
        density = soil_settings["sample_density"]
        grid_m = units.distance_to_meters(soil_settings["surface_grid_size"])
        estimates["soil_points"] = max(1, int(math.ceil(area_display / density))) * soil_year_count
        if soil_settings["create_surface"] and not soil_settings["unattributed"]:
            estimates["soil_surface_cells"] = _surface_cells(area_m2, grid_m) * soil_year_count

    if enabled.get("planting"):
        planter_width_m = units.distance_to_meters(planting_settings["planter_width"])
        planting_speed_mps = units.speed_to_meters_per_second(
            planting_settings["nominal_speed"]
        )
        center_per_year = _machine_points(
            area_m2,
            planter_width_m,
            planting_speed_mps,
            planting_settings["logging_interval"],
        )
        if planting_settings["point_output"] in {"Planter Center", "Both"}:
            estimates["planter_center_points"] = center_per_year * len(selected_years)
        if planting_settings["point_output"] in {"Row Units", "Both"}:
            estimates["planting_row_unit_points"] = (
                center_per_year * planting_settings["row_units"] * len(selected_years)
            )
        if planting_settings["create_surface"]:
            grid_m = units.distance_to_meters(planting_settings["surface_grid_size"])
            estimates["planting_surface_cells"] = _surface_cells(area_m2, grid_m) * len(
                selected_years
            )

    if enabled.get("applications"):
        for operation in application_operations:
            width_m = units.distance_to_meters(operation["equipment_width"])
            speed_mps = units.speed_to_meters_per_second(operation["nominal_speed"])
            estimates["application_points"] += _machine_points(
                area_m2, width_m, speed_mps, operation["logging_interval"]
            )
            if operation.get("create_surface", True):
                grid_m = units.distance_to_meters(operation["surface_grid_size"])
                estimates["application_surface_cells"] += _surface_cells(area_m2, grid_m)

    if enabled.get("yield"):
        swath_width_m = units.distance_to_meters(yield_settings["swath_width"])
        harvest_speed_mps = units.speed_to_meters_per_second(
            yield_settings["nominal_speed"]
        )
        points_per_year = _machine_points(
            area_m2,
            swath_width_m,
            harvest_speed_mps,
            yield_settings["logging_interval"],
        )
        estimates["yield_points"] = points_per_year * len(selected_years)
        if yield_settings["create_surface"]:
            grid_m = units.distance_to_meters(yield_settings["surface_grid_size"])
            estimates["yield_surface_cells"] = _surface_cells(area_m2, grid_m) * len(
                selected_years
            )

    estimates["total_points"] = sum(
        value for key, value in estimates.items() if key.endswith("points")
    )
    estimates["total_surface_cells"] = sum(
        value for key, value in estimates.items() if key.endswith("surface_cells")
    )
    estimates["total_records"] = estimates["total_points"] + estimates["total_surface_cells"]
    return estimates
