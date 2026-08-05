# SPDX-License-Identifier: GPL-3.0-or-later
"""Human-readable complete-run preflight summaries."""

from __future__ import annotations

from pathlib import Path

from .progress import format_duration


FAKE_WARNING = "FAKE DATA - FOR TESTING AND DEMONSTRATION ONLY - NOT FOR AGRONOMIC DECISIONS"

DATA_TYPE_LABELS = {
    "soil": "Soil tests",
    "planting": "Planting",
    "applications": "As-applied",
    "yield": "Yield",
}

ESTIMATE_LABELS = (
    ("soil_points", "Soil-test points"),
    ("soil_surface_cells", "Soil surface cells"),
    ("planter_center_points", "Planter-center points"),
    ("planting_row_unit_points", "Planting row-unit points"),
    ("planting_surface_cells", "Planting surface cells"),
    ("application_points", "Application points"),
    ("application_surface_cells", "Application surface cells"),
    ("yield_points", "Yield points"),
    ("yield_surface_cells", "Yield surface cells"),
)


def runtime_warning(total_records):
    """Return a stable qualitative warning for the estimated record count."""

    total = max(0, int(total_records))
    if total >= 1_000_000:
        return "Very large run: expect substantial processing time and disk use."
    if total >= 100_000:
        return "Large run: processing may take a while and use significant disk space."
    return "Normal-sized run: actual time still depends on field geometry and output formats."


def estimate_runtime_range(estimates, output_formats=None, review_max_features=20_000):
    """Return a conservative local runtime range from requested record types.

    The estimate is intentionally a range because polygon complexity, storage speed,
    QGIS/GDAL versions, interpolation, and antivirus scanning can materially change
    throughput. The weights reflect the relative work performed by the generators.
    """

    values = {key: max(0, int(value or 0)) for key, value in dict(estimates).items()}
    # Calibrated against the optimized OGR bulk-consolidation, streamed HTML
    # review, and batched point-attribute paths. A 35k-point yield benchmark fell
    # from 4.21 to 2.96 seconds; the 355k-record reference run is expected near
    # 42 to 44 seconds on the same workstation.
    seconds = 5.0
    rates = {
        "soil_points": 4_000.0,
        "soil_surface_cells": 1_000.0,
        "planter_center_points": 20_000.0,
        "planting_row_unit_points": 30_000.0,
        "planting_surface_cells": 7_000.0,
        "application_points": 20_000.0,
        "application_surface_cells": 7_000.0,
        "yield_points": 20_000.0,
        "yield_surface_cells": 7_000.0,
    }
    for key, rate in rates.items():
        seconds += values.get(key, 0) / rate

    formats = list(output_formats or ["GeoPackage"])
    seconds *= 1.0 + 0.20 * max(0, len(formats) - 1)
    visible_records = min(
        values.get("total_records", 0),
        max(100, int(review_max_features)) * max(1, sum(values.get(key, 0) > 0 for key in rates)),
    )
    seconds += visible_records / 40_000.0
    lower = max(3, int(round(seconds * 0.75)))
    upper = max(lower + 3, int(round(seconds * 1.80)))
    return lower, upper


def runtime_estimate_text(estimates, output_formats=None, review_max_features=20_000):
    """Format the pre-run heuristic as a user-facing range."""

    lower, upper = estimate_runtime_range(
        estimates, output_formats, review_max_features
    )
    return f"about {format_duration(lower)} to {format_duration(upper)}"


def build_preflight_review_text(
    *,
    field_count,
    used_selection,
    area_text,
    years,
    enabled,
    estimates,
    output_formats,
    operation_count,
    crop_mode,
    crop_review_status,
    network_requirement,
    output_directory,
    timezone_label,
    review_max_features,
    runtime_estimate=None,
):
    """Build the complete review-page text shown before any generation starts."""

    selected_types = [
        label for key, label in DATA_TYPE_LABELS.items() if bool(enabled.get(key))
    ]
    year_text = ", ".join(str(int(year)) for year in years)
    selection_text = "selected polygon features only" if used_selection else "all layer features"
    format_text = ", ".join(str(value) for value in output_formats) or "None"
    type_text = ", ".join(selected_types) or "None"
    timezone_text = str(timezone_label).strip() or "Not supplied"
    destination = str(Path(output_directory))

    lines = [
        FAKE_WARNING,
        "",
        "RUN SCOPE",
        f"Fields: {int(field_count):,} ({selection_text})",
        f"Area: {area_text}",
        f"Years: {year_text}",
        f"Data types: {type_text}",
        f"Application operations after year expansion: {int(operation_count):,}",
        f"Timestamp timezone label: {timezone_text}",
        "",
        "CROP REVIEW AND NETWORK",
        f"Crop mode: {crop_mode}",
        f"Crop review: {crop_review_status}",
        f"Network requirement: {network_requirement}",
        "",
        "ESTIMATED OUTPUT RECORDS",
    ]
    for key, label in ESTIMATE_LABELS:
        lines.append(f"{label}: {int(estimates.get(key, 0)):,}")
    lines.extend(
        [
            f"Total points: {int(estimates.get('total_points', 0)):,}",
            f"Total surface cells: {int(estimates.get('total_surface_cells', 0)):,}",
            f"Total records: {int(estimates.get('total_records', 0)):,}",
            f"Estimated runtime: {runtime_estimate or 'not calculated'}",
            "",
            "OUTPUTS",
            f"Formats: {format_text}",
            f"Parent destination: {destination}",
            f"HTML review feature limit per high-volume layer: {int(review_max_features):,}",
            "Every soil-test point is included even when it exceeds that limit.",
            "Every successful run creates a portable HTML comparison review.",
            "",
            "WARNINGS",
            runtime_warning(estimates.get("total_records", 0)),
            "QGIS must remain open until processing finishes.",
            "Review the settings above, then choose Run Reviewed Configuration.",
        ]
    )
    return "\n".join(lines)
