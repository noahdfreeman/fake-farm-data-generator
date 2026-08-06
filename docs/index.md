---
layout: default
title: Fake Farm Data Generator
---

# Fake Farm Data Generator

Fake Farm Data Generator is an open-source QGIS plugin for producing clearly
labeled fake soil-test, planting, as-applied, and yield data. It is designed for
software development, demonstrations, screenshots, training, and workflow tests
where real grower data must not be used.

> **FAKE DATA — FOR TESTING AND DEMONSTRATION ONLY — NOT FOR AGRONOMIC DECISIONS**

The plugin provides a seven-tab complete-run workflow and four independent QGIS
Processing algorithms. The complete workflow opens directly from its Processing
Toolbox entry, with ordinary controls instead of JSON settings. A complete run
can cover up to 20 fields, 5,000 total acres, and 10 crop years.

## Documentation

- [Installation](installation.md)
- [Complete-run workflow](complete-run.md)
- [Individual Processing tools](individual-tools.md)
- [Parameter reference](parameters.md)
- [Output schemas](schemas.md)
- [Crop lookup and privacy](crop-sources.md)
- [Outputs and portable review](outputs-and-review.md)
- [Demonstration run](demo/index.md)
- [Development and releases](development-and-release.md)

## What a run can create

| Data type | Point output | Polygon-grid output |
| --- | --- | --- |
| Soil tests | Grid or random sample locations | IDW or ordinary-kriging nutrient surface |
| Planting | Planter-center, row-unit, or both | Population, speed, seed spacing, and seed depth |
| As-applied | Machine-center application log | Actual rate, speed, and fake-terrain effect |
| Yield | Combine-style monitor log | Dry yield, wet yield, moisture, and speed |

GeoPackage is the canonical output. Optional Shapefile, GeoJSON, point CSV, and
surface GeoTIFF derivatives are available. Every successful run also creates a
portable Leaflet review with filters, independent left/right layer selection,
and a draggable comparison divider.

## Current release status

Version 1.0.1 includes weighted incremental progress, a pre-run runtime range and
completion actions, clickable all-field background boundaries, compare-off
startup, a data-opacity control, data-type-specific default attributes, and natural
field-wide yield patterns with full-perimeter headland passes. It also places the
required output directory first, uses headland pass counts with matched planting
and yield widths, enforces a 150-foot default soil-point setback, and rounds review
area totals to tenths. It keeps the left
layer visible when comparison is disabled and shows one selected field's data at a
time with automatic field zoom. It retains the isolated worker, streamed progress, multi-layer
boundaries, crop controls, and advanced planter metrics. See
`V1_IMPLEMENTATION_STATUS.md` for current compatibility evidence.
