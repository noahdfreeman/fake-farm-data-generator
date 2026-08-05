# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure-Python deterministic generation helpers."""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from datetime import date, timedelta
from typing import Iterable, List, Sequence, Tuple


FAKE_WARNING = "FAKE DATA - NOT FOR AGRONOMIC DECISIONS"

VARIABILITY_MULTIPLIERS = {
    "Low": 0.5,
    "Medium": 1.5,
    "High": 3.0,
}

_TIMEZONE_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


def normalize_timezone_label(value: object) -> str:
    """Return an optional, safe timezone label for timestamp provenance.

    The generators intentionally write local, offset-free fake operation times.
    This label records the user's intended timezone without changing those
    deterministic timestamps or depending on operating-system timezone data.
    """

    text = "" if value is None else str(value).strip()
    if len(text) > 100:
        raise ValueError("Timezone must be no more than 100 characters")
    if _TIMEZONE_CONTROL_CHARACTERS.search(text):
        raise ValueError("Timezone cannot contain control characters")
    return text


def feature_field_id(feature, index: int) -> str:
    """Return a stable carried field ID or the deterministic generated fallback."""

    field_names = set(feature.fields().names()) if feature is not None else set()
    for name in ("field_id", "ffdg_field_id"):
        if name not in field_names:
            continue
        value = feature.attribute(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"Field_{int(index):03d}"


def feature_field_identity(feature, index: int, mapping=None):
    """Carry conventional field identity columns with deterministic fallbacks."""

    mapping = mapping or {}
    names = feature.fields().names() if feature is not None else []
    casefolded = {str(name).casefold(): str(name) for name in names}

    def first_value(*aliases, mapped_name=""):
        candidates = ([mapped_name] if str(mapped_name or "").strip() else []) + list(aliases)
        for alias in candidates:
            source_name = casefolded.get(str(alias).casefold())
            if source_name is None:
                continue
            value = feature.attribute(source_name)
            text = "" if value is None else str(value).strip()
            if text and text.casefold() not in {"null", "none"}:
                return text
        return ""

    field_id = first_value(
        "field_id",
        "ffdg_field_id",
        mapped_name=mapping.get("field_id", ""),
    ) or f"Field_{int(index):03d}"

    return {
        "field_id": field_id,
        "field_name": first_value(
            "field_name", "field", "name", mapped_name=mapping.get("field_name", "")
        ) or field_id,
        "farm_name": first_value(
            "farm_name", "farm", mapped_name=mapping.get("farm_name", "")
        ),
        "grower_name": first_value(
            "grower_name",
            "grower",
            "operator_name",
            mapped_name=mapping.get("grower_name", ""),
        ),
    }


def crop_provenance_from_json(text: str, crop_name: str, year: int):
    """Normalize optional crop provenance passed between Processing algorithms."""

    defaults = {
        "crop_name": str(crop_name),
        "crop_code": "",
        "crop_pct": 0.0,
        "crop_source": "manual",
        "crop_source_year": int(year),
        "crop_resolution": None,
        "crop_lookup_at": "",
        "crop_overridden": False,
    }
    if not str(text or "").strip():
        return defaults
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Crop provenance JSON must be an object")
    for key in defaults:
        if key in payload:
            defaults[key] = payload[key]
    defaults["crop_name"] = str(crop_name)
    defaults["crop_source_year"] = int(defaults["crop_source_year"] or year)
    defaults["crop_pct"] = float(defaults["crop_pct"] or 0.0)
    defaults["crop_overridden"] = bool(defaults["crop_overridden"])
    return defaults


def stable_seed(master_seed: int, *parts: object) -> int:
    """Derive a stable positive 31-bit child seed."""

    payload = "|".join(str(part) for part in (master_seed,) + parts)
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 2_147_483_647 or 1


def parse_years(text: str, maximum: int = 10) -> List[int]:
    """Parse comma-separated years and inclusive ranges into sorted years."""

    years = set()
    for raw_token in (text or "").split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())
            if end < start:
                raise ValueError(f"Year range ends before it starts: {token}")
            years.update(range(start, end + 1))
        else:
            years.add(int(token))
    ordered = sorted(years)
    if not ordered:
        raise ValueError("At least one year is required")
    if len(ordered) > maximum:
        raise ValueError(f"No more than {maximum} years may be selected")
    if ordered[0] < 1900 or ordered[-1] > 2100:
        raise ValueError("Years must be between 1900 and 2100")
    return ordered


def deterministic_operation_date(
    year: int,
    month: int,
    day: int,
    window_days: int,
    seed: int,
) -> date:
    """Return a stable date varied inside the inclusive configured window."""

    base = date(year, month, day)
    window = max(0, int(window_days))
    rng = random.Random(seed)
    return base + timedelta(days=rng.randint(-window, window))


def idw_value(
    samples: Iterable[Tuple[float, float, float]],
    x: float,
    y: float,
    power: float = 2.0,
    max_neighbors: int = 8,
) -> Tuple[float, int]:
    """Interpolate a value and return the number of contributing samples."""

    candidates: List[Tuple[float, float]] = []
    for sample_x, sample_y, value in samples:
        distance = math.hypot(sample_x - x, sample_y - y)
        if distance <= 1e-12:
            return float(value), 1
        candidates.append((distance, float(value)))
    if not candidates:
        raise ValueError("IDW requires at least one sample")
    candidates.sort(key=lambda item: item[0])
    limit = max(1, int(max_neighbors))
    selected = candidates[:limit]
    exponent = max(0.1, float(power))
    weighted_sum = 0.0
    weight_sum = 0.0
    for distance, value in selected:
        weight = 1.0 / (distance**exponent)
        weighted_sum += value * weight
        weight_sum += weight
    return weighted_sum / weight_sum, len(selected)


def semivariance(
    distance: float,
    model: str,
    range_distance: float,
    nugget_ratio: float = 0.0,
) -> float:
    """Return a normalized theoretical semivariance for a separation distance."""

    separation = max(0.0, float(distance))
    if separation <= 1e-12:
        return 0.0
    effective_range = max(1e-9, float(range_distance))
    nugget = max(0.0, min(1.0, float(nugget_ratio)))
    partial_sill = 1.0 - nugget
    ratio = separation / effective_range
    normalized_model = str(model).strip().lower()
    if normalized_model == "spherical":
        structured = 1.0 if ratio >= 1.0 else 1.5 * ratio - 0.5 * ratio**3
    elif normalized_model == "exponential":
        # The factor of three makes the configured range the practical range.
        structured = 1.0 - math.exp(-3.0 * ratio)
    elif normalized_model == "gaussian":
        structured = 1.0 - math.exp(-3.0 * ratio**2)
    else:
        raise ValueError(f"Unsupported variogram model: {model}")
    return nugget + partial_sill * structured


def _solve_linear_system(matrix: Sequence[Sequence[float]], values: Sequence[float]):
    """Solve a small dense system using pivoted Gauss-Jordan elimination."""

    size = len(values)
    if size == 0 or len(matrix) != size or any(len(row) != size for row in matrix):
        raise ValueError("Linear system dimensions do not match")
    augmented = [
        [float(item) for item in matrix[row_index]] + [float(values[row_index])]
        for row_index in range(size)
    ]
    for column in range(size):
        pivot_row = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        pivot = augmented[pivot_row][column]
        if abs(pivot) <= 1e-12:
            raise ValueError("Kriging system is singular")
        if pivot_row != column:
            augmented[column], augmented[pivot_row] = (
                augmented[pivot_row],
                augmented[column],
            )
        pivot = augmented[column][column]
        augmented[column] = [item / pivot for item in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if abs(factor) <= 1e-15:
                continue
            augmented[row] = [
                augmented[row][item] - factor * augmented[column][item]
                for item in range(size + 1)
            ]
    return [augmented[row][-1] for row in range(size)]


def ordinary_kriging_weights(
    sample_locations: Iterable[Tuple[float, float]],
    x: float,
    y: float,
    model: str = "Spherical",
    range_distance: float = 1.0,
    nugget_ratio: float = 0.0,
    max_neighbors: int = 12,
) -> Tuple[List[int], List[float], float]:
    """Return source indexes, ordinary-kriging weights, and kriging variance."""

    locations = [(float(sx), float(sy)) for sx, sy in sample_locations]
    if not locations:
        raise ValueError("Ordinary kriging requires at least one sample")
    candidates = []
    for index, (sample_x, sample_y) in enumerate(locations):
        distance = math.hypot(sample_x - x, sample_y - y)
        if distance <= 1e-12:
            return [index], [1.0], 0.0
        candidates.append((distance, index))
    candidates.sort(key=lambda item: item[0])
    selected = candidates[: max(1, int(max_neighbors))]
    if len(selected) == 1:
        return [selected[0][1]], [1.0], semivariance(
            selected[0][0], model, range_distance, nugget_ratio
        )

    indexes = [index for _distance, index in selected]
    count = len(indexes)
    matrix = [[0.0] * (count + 1) for _ in range(count + 1)]
    right_hand_side = [0.0] * (count + 1)
    for row, source_index in enumerate(indexes):
        source_x, source_y = locations[source_index]
        for column, neighbor_index in enumerate(indexes):
            neighbor_x, neighbor_y = locations[neighbor_index]
            matrix[row][column] = semivariance(
                math.hypot(source_x - neighbor_x, source_y - neighbor_y),
                model,
                range_distance,
                nugget_ratio,
            )
        matrix[row][count] = 1.0
        matrix[count][row] = 1.0
        right_hand_side[row] = semivariance(
            math.hypot(source_x - x, source_y - y),
            model,
            range_distance,
            nugget_ratio,
        )
    right_hand_side[count] = 1.0
    solution = _solve_linear_system(matrix, right_hand_side)
    weights = solution[:count]
    kriging_variance = sum(
        weight * right_hand_side[index] for index, weight in enumerate(weights)
    ) + solution[count]
    return indexes, weights, max(0.0, kriging_variance)


def ordinary_kriging_value(
    samples: Iterable[Tuple[float, float, float]],
    x: float,
    y: float,
    model: str = "Spherical",
    range_distance: float = 1.0,
    nugget_ratio: float = 0.0,
    max_neighbors: int = 12,
) -> Tuple[float, int, float]:
    """Interpolate one value with ordinary kriging."""

    materialized = [(float(sx), float(sy), float(value)) for sx, sy, value in samples]
    indexes, weights, variance = ordinary_kriging_weights(
        ((sx, sy) for sx, sy, _value in materialized),
        x,
        y,
        model,
        range_distance,
        nugget_ratio,
        max_neighbors,
    )
    value = sum(weights[position] * materialized[index][2] for position, index in enumerate(indexes))
    return value, len(indexes), variance


def estimate_machine_points(
    area_square_meters: float,
    swath_width_meters: float,
    point_spacing_meters: float,
) -> int:
    """Estimate center-log points from area and nominal coverage dimensions."""

    footprint = max(0.01, swath_width_meters) * max(0.01, point_spacing_meters)
    return max(1, int(math.ceil(max(0.0, area_square_meters) / footprint)))
