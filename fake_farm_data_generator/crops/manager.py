# SPDX-License-Identifier: GPL-3.0-or-later
"""Coordinate local/remote CDL sources and manual field-year review decisions."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QStandardPaths
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
)

from .resolver import CropAssignment, apply_manual_override, classify_histogram
from .sources.croplandcros import CroplandCrosSource
from .sources.local_cdl import raster_histogram


def default_cache_directory():
    cache_location = getattr(QStandardPaths, "CacheLocation", None)
    if cache_location is None:
        cache_location = QStandardPaths.StandardLocation.CacheLocation
    base = QStandardPaths.writableLocation(cache_location)
    return Path(base) / "fake_farm_data_generator" / "cdl"


def parse_overrides(text, allowed_profiles):
    """Parse nested or `Field_001:2024` manual crop mappings."""

    if not str(text or "").strip():
        return {}
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Crop overrides JSON must be an object")
    normalized = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            field_id = str(key)
            for year, crop_name in value.items():
                normalized[(field_id, int(year))] = str(crop_name)
        else:
            key_text = str(key)
            if ":" not in key_text:
                raise ValueError(
                    "Flat crop override keys must use Field_001:2024"
                )
            field_id, year = key_text.rsplit(":", 1)
            normalized[(field_id, int(year))] = str(value)
    invalid = sorted({crop for crop in normalized.values() if crop not in allowed_profiles})
    if invalid:
        raise ValueError(f"Unsupported crop override profile(s): {', '.join(invalid)}")
    return normalized


def parse_assignment_payload(text, allowed_profiles):
    """Parse complete API/inference assignments supplied by the custom dialog."""

    if not str(text or "").strip():
        return {}
    raw_text = str(text).strip()
    if raw_text.startswith("@"):
        raw_text = Path(raw_text[1:]).read_text(encoding="utf-8")
    payload = json.loads(raw_text)
    if not isinstance(payload, dict):
        raise ValueError("Crop assignment payload must be an object")
    assignments = {}
    for key, raw in payload.items():
        if ":" not in str(key) or not isinstance(raw, dict):
            raise ValueError("Crop assignment keys must use Field_001:2025 objects")
        field_id, year_text = str(key).rsplit(":", 1)
        crop_name = raw.get("crop_name")
        if crop_name not in allowed_profiles:
            raise ValueError(f"Unsupported crop assignment for {key}: {crop_name}")
        assignment = CropAssignment(
            crop_name=str(crop_name),
            crop_code=(int(raw["crop_code"]) if raw.get("crop_code") is not None else None),
            crop_pct=float(raw.get("crop_pct", 0.0)),
            crop_source=str(raw.get("crop_source", "croplandcros")),
            crop_source_year=int(raw.get("crop_source_year", year_text)),
            crop_resolution=(
                float(raw["crop_resolution"])
                if raw.get("crop_resolution") is not None
                else None
            ),
            crop_lookup_at=str(
                raw.get("crop_lookup_at")
                or datetime.now().astimezone().isoformat(timespec="seconds")
            ),
            crop_overridden=bool(raw.get("crop_overridden", False)),
            cdl_class_name=(
                str(raw["cdl_class_name"])
                if raw.get("cdl_class_name") is not None
                else None
            ),
            status=str(raw.get("status", "accepted")),
            review_required=False,
            valid_agricultural_pixels=int(raw.get("valid_agricultural_pixels", 0)),
            total_pixels=int(raw.get("total_pixels", 0)),
        )
        assignments[(field_id, int(year_text))] = assignment
    return assignments


def _rotation_assignment(known, year):
    """Infer a missing crop from nearby API observations with explicit provenance."""

    usable = {int(value): item for value, item in known.items() if item.crop_name}
    if not usable:
        return None
    nearest_year = min(usable, key=lambda value: (abs(value - int(year)), -value))
    nearest = usable[nearest_year]
    crop_names = {item.crop_name for item in usable.values()}
    crop_name = nearest.crop_name
    if crop_names <= {"Corn", "Soybeans"}:
        if abs(int(year) - nearest_year) % 2:
            crop_name = "Soybeans" if nearest.crop_name == "Corn" else "Corn"
    else:
        for period in (2, 3, 4):
            comparisons = [
                usable[value].crop_name == usable[value - period].crop_name
                for value in usable
                if value - period in usable
            ]
            if comparisons and all(comparisons):
                matching = [
                    value for value in usable if (value - int(year)) % period == 0
                ]
                if matching:
                    reference = min(
                        matching, key=lambda value: abs(value - int(year))
                    )
                    crop_name = usable[reference].crop_name
                    nearest_year = reference
                    nearest = usable[reference]
                break
    return CropAssignment(
        crop_name=crop_name,
        crop_code=None,
        crop_pct=0.0,
        crop_source="rotation_inference",
        crop_source_year=nearest_year,
        crop_resolution=nearest.crop_resolution,
        crop_lookup_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        crop_overridden=False,
        cdl_class_name=None,
        status="inferred_rotation",
        review_required=False,
        valid_agricultural_pixels=0,
        total_pixels=0,
    )


def suggest_api_field_year_assignments(
    features,
    source_crs,
    transform_context,
    years,
    allowed_profiles,
    feedback=None,
):
    """Pull USDA CDL through the API and infer unavailable years from rotation."""

    feature_list = list(features)
    selected_years = sorted({int(year) for year in years})
    if not feature_list or not selected_years:
        return {}, []
    assignments = {}
    issues = []
    with tempfile.TemporaryDirectory(prefix="ffdg_cdl_api_") as temporary:
        remote = CroplandCrosSource(Path(temporary))
        available = set(remote.available_years())
        context_start = max(1900, selected_years[0] - 3)
        lookup_years = [
            year
            for year in range(context_start, selected_years[-1] + 1)
            if year in available
        ]
        field_extents = [
            web_mercator_extent(
                feature, source_crs, transform_context, padding=30.0
            )
            for feature in feature_list
        ]
        combined_extent = (
            min(extent[0] for extent in field_extents),
            min(extent[1] for extent in field_extents),
            max(extent[2] for extent in field_extents),
            max(extent[3] for extent in field_extents),
        )
        known_by_field = {index: {} for index in range(len(feature_list))}
        errors_by_field = {index: {} for index in range(len(feature_list))}

        def classify_for_field(field_index, feature, lookup_year, raster_path):
            histogram, resolution = raster_histogram(
                raster_path,
                feature.geometry(),
                source_crs,
                transform_context,
            )
            assignment = classify_histogram(
                histogram, "croplandcros", lookup_year, resolution
            )
            if assignment.crop_name not in allowed_profiles:
                return
            if assignment.review_required:
                assignment = replace(
                    assignment,
                    status="api_estimate",
                    review_required=False,
                )
            known_by_field[field_index][lookup_year] = assignment
            if feedback is not None:
                feedback.pushInfo(
                    f"Field_{field_index + 1:03d} {lookup_year}: "
                    f"{assignment.crop_name} from USDA CDL "
                    f"({assignment.crop_pct:.1f}%)"
                )

        for lookup_year in lookup_years:
            try:
                raster_path, _source_name, _details = remote.fetch(
                    lookup_year, combined_extent, 30.0
                )
                for field_index, feature in enumerate(feature_list):
                    classify_for_field(field_index, feature, lookup_year, raster_path)
                continue
            except Exception as combined_error:
                combined_error_text = str(combined_error)
                if feedback is not None:
                    feedback.pushInfo(
                        f"Combined CDL request for {lookup_year} was unavailable; "
                        "trying field-sized requests"
                    )
            for field_index, (feature, extent) in enumerate(
                zip(feature_list, field_extents)
            ):
                try:
                    raster_path, _source_name, _details = remote.fetch(
                        lookup_year, extent, 30.0
                    )
                    classify_for_field(
                        field_index, feature, lookup_year, raster_path
                    )
                except Exception as error:
                    errors_by_field[field_index][lookup_year] = (
                        f"combined: {combined_error_text}; field: {error}"
                    )

        for field_index, _feature in enumerate(feature_list, start=1):
            field_id = f"Field_{field_index:03d}"
            known = known_by_field[field_index - 1]
            errors_by_year = errors_by_field[field_index - 1]
            for selected_year in selected_years:
                assignment = known.get(selected_year)
                if assignment is None:
                    assignment = _rotation_assignment(known, selected_year)
                if assignment is not None:
                    assignments[(field_id, selected_year)] = assignment
                else:
                    issues.append(
                        {
                            "field_id": field_id,
                            "year": selected_year,
                            "status": "lookup_failed",
                            "dominant_class": None,
                            "crop_pct": 0.0,
                            "errors": [
                                errors_by_year.get(selected_year)
                                or "No usable CDL year was available for rotation inference"
                            ],
                        }
                    )
    return assignments, issues


def find_local_raster(path_text, year, requested_years):
    if not str(path_text or "").strip():
        return None
    path = Path(path_text)
    if path.is_file():
        return path if len(requested_years) == 1 else None
    if not path.is_dir():
        return None
    candidates = []
    for pattern in (f"*{int(year)}*.tif", f"*{int(year)}*.tiff"):
        candidates.extend(path.glob(pattern))
    return sorted(set(candidates))[0] if candidates else None


def web_mercator_extent(feature, source_crs, transform_context, padding=30.0):
    geometry = QgsGeometry(feature.geometry())
    target = QgsCoordinateReferenceSystem("EPSG:3857")
    if source_crs != target:
        geometry.transform(QgsCoordinateTransform(source_crs, target, transform_context))
    bbox = geometry.boundingBox()
    margin = max(0.0, float(padding))
    return (
        bbox.xMinimum() - margin,
        bbox.yMinimum() - margin,
        bbox.xMaximum() + margin,
        bbox.yMaximum() + margin,
    )


def resolve_field_year_assignments(
    features,
    source_crs,
    transform_context,
    years,
    mode,
    manual_profile,
    overrides_text,
    allowed_profiles,
    local_raster_path="",
    cache_directory="",
    feedback=None,
):
    """Resolve all assignments or raise with the exact entries needing review."""

    overrides = parse_overrides(overrides_text, allowed_profiles)
    suggestions, suggestion_issues = suggest_field_year_assignments(
        features,
        source_crs,
        transform_context,
        years,
        mode,
        manual_profile,
        allowed_profiles,
        local_raster_path,
        cache_directory,
        feedback,
    )
    assignments = {}
    unresolved = []
    issue_by_key = {
        (item["field_id"], int(item["year"])): item
        for item in suggestion_issues
    }
    for field_index, _feature in enumerate(features, start=1):
        field_id = f"Field_{field_index:03d}"
        for year in years:
            override = overrides.get((field_id, year))
            assignment = suggestions.get((field_id, year))
            if override:
                assignment = apply_manual_override(assignment, override, year)
            if assignment is None or assignment.review_required:
                unresolved.append(issue_by_key.get(
                    (field_id, year),
                    {
                        "field_id": field_id,
                        "year": year,
                        "status": assignment.status if assignment else "lookup_failed",
                        "dominant_class": assignment.cdl_class_name if assignment else None,
                        "crop_pct": assignment.crop_pct if assignment else 0.0,
                        "errors": [],
                    },
                ))
            else:
                assignments[(field_id, year)] = assignment
    if unresolved:
        required = {
            f"{item['field_id']}:{item['year']}": manual_profile for item in unresolved
        }
        detail = json.dumps(unresolved, indent=2)
        example = json.dumps(required, separators=(",", ":"))
        raise ValueError(
            "Crop review is required before generation. Add reviewed entries to "
            f"Crop overrides JSON, for example: {example}\nDetails:\n{detail}"
        )
    return assignments


def suggest_field_year_assignments(
    features,
    source_crs,
    transform_context,
    years,
    mode,
    manual_profile,
    allowed_profiles,
    local_raster_path="",
    cache_directory="",
    feedback=None,
):
    """Return reviewable crop suggestions without requiring manual decisions.

    The returned assignment mapping includes below-threshold and ambiguous CDL
    classifications so a GUI can display their provenance. Lookup failures are
    represented in the accompanying issues list and are intentionally not
    converted into a guessed crop.
    """

    if manual_profile not in allowed_profiles:
        raise ValueError(f"Unsupported manual crop profile: {manual_profile}")
    feature_list = list(features)
    year_list = [int(year) for year in years]
    assignments = {}
    issues = []
    if str(mode) == "Manual profile":
        for field_index, _feature in enumerate(feature_list, start=1):
            field_id = f"Field_{field_index:03d}"
            for year in year_list:
                assignments[(field_id, year)] = apply_manual_override(
                    None, manual_profile, year
                )
        return assignments, issues

    cache_root = (
        Path(cache_directory)
        if str(cache_directory or "").strip()
        else default_cache_directory()
    )
    remote = CroplandCrosSource(cache_root)
    for field_index, feature in enumerate(feature_list, start=1):
        field_id = f"Field_{field_index:03d}"
        for year in year_list:
            assignment = None
            errors = []
            extent = web_mercator_extent(
                feature, source_crs, transform_context, padding=30.0
            )
            cached = remote.cached(year, extent, 30.0)
            if cached is not None:
                try:
                    raster_path, source_name, _details = cached
                    histogram, resolution = raster_histogram(
                        raster_path,
                        feature.geometry(),
                        source_crs,
                        transform_context,
                    )
                    assignment = classify_histogram(
                        histogram, source_name, year, resolution
                    )
                except Exception as error:
                    errors.append(f"cache: {error}")
            if assignment is None:
                local = find_local_raster(local_raster_path, year, year_list)
                if local is not None:
                    try:
                        histogram, resolution = raster_histogram(
                            local,
                            feature.geometry(),
                            source_crs,
                            transform_context,
                        )
                        assignment = classify_histogram(
                            histogram, "local_cdl", year, resolution
                        )
                    except Exception as error:
                        errors.append(f"local CDL: {error}")
            if assignment is None:
                try:
                    raster_path, source_name, _details = remote.fetch(
                        year, extent, 30.0
                    )
                    histogram, resolution = raster_histogram(
                        raster_path,
                        feature.geometry(),
                        source_crs,
                        transform_context,
                    )
                    assignment = classify_histogram(
                        histogram, source_name, year, resolution
                    )
                except Exception as error:
                    errors.append(f"CroplandCROS: {error}")

            if assignment is not None:
                assignments[(field_id, year)] = assignment
                if feedback is not None:
                    suffix = " - review required" if assignment.review_required else ""
                    feedback.pushInfo(
                        f"{field_id} {year}: {assignment.crop_name or assignment.cdl_class_name or 'unresolved'} "
                        f"from {assignment.crop_source} ({assignment.crop_pct:.1f}% of agricultural pixels){suffix}"
                    )
            if assignment is None or assignment.review_required:
                issues.append(
                    {
                        "field_id": field_id,
                        "year": year,
                        "status": assignment.status if assignment else "lookup_failed",
                        "dominant_class": assignment.cdl_class_name if assignment else None,
                        "crop_pct": assignment.crop_pct if assignment else 0.0,
                        "errors": errors,
                    }
                )
    return assignments, issues
