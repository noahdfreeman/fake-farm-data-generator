# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared display-unit conversions for generator inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass


UNIT_SYSTEM_OPTIONS = ["Imperial", "Metric"]
SQUARE_METERS_PER_ACRE = 4046.8564224
SQUARE_METERS_PER_HECTARE = 10000.0

METRIC_YIELD = {
    "Corn": (0.0627704, "t/ha"),
    "Soybeans": (0.0672511, "t/ha"),
    "Wheat": (0.0672511, "t/ha"),
    "Cotton": (537.849, "kg/ha"),
    "Grain Sorghum": (0.0627704, "t/ha"),
    "Barley": (0.053799, "t/ha"),
    "Oats": (0.035870, "t/ha"),
    "Canola": (0.056043, "t/ha"),
    "Dry Beans": (112.085, "kg/ha"),
    "Sunflowers": (1.12085, "kg/ha"),
    "Alfalfa": (2.24170, "t/ha"),
    "Other Crop": (2.47105, "units/ha"),
}


@dataclass(frozen=True)
class UnitSystem:
    name: str

    @property
    def metric(self):
        return self.name == "Metric"

    @property
    def distance_unit(self):
        return "m" if self.metric else "ft"

    @property
    def small_distance_unit(self):
        return "cm" if self.metric else "in"

    @property
    def speed_unit(self):
        return "km/h" if self.metric else "mph"

    @property
    def area_unit(self):
        return "ha" if self.metric else "acre"

    @property
    def population_unit(self):
        return "seeds/ha" if self.metric else "seeds/acre"

    def distance_to_meters(self, value):
        return float(value) if self.metric else float(value) * 0.3048

    def small_distance_to_meters(self, value):
        return float(value) / 100.0 if self.metric else float(value) * 0.0254

    def speed_to_meters_per_second(self, value):
        return float(value) / 3.6 if self.metric else float(value) * 0.44704

    def area_from_square_meters(self, value):
        divisor = SQUARE_METERS_PER_HECTARE if self.metric else SQUARE_METERS_PER_ACRE
        return float(value) / divisor

    def population_per_square_meter(self, value):
        divisor = SQUARE_METERS_PER_HECTARE if self.metric else SQUARE_METERS_PER_ACRE
        return float(value) / divisor

    def small_distance_from_meters(self, value):
        return float(value) * 100.0 if self.metric else float(value) / 0.0254

    def seed_spacing(self, population, row_spacing):
        per_square_meter = max(1e-12, self.population_per_square_meter(population))
        row_spacing_m = max(1e-12, self.small_distance_to_meters(row_spacing))
        return self.small_distance_from_meters(1.0 / (per_square_meter * row_spacing_m))


def unit_system(value):
    if isinstance(value, int):
        name = UNIT_SYSTEM_OPTIONS[value]
    else:
        name = str(value)
    if name not in UNIT_SYSTEM_OPTIONS:
        raise ValueError(f"Unsupported unit system: {name}")
    return UnitSystem(name)


def metric_yield_profile(crop_name, minimum, maximum, imperial_unit):
    factor, metric_unit = METRIC_YIELD[str(crop_name)]
    return float(minimum) * factor, float(maximum) * factor, metric_unit
