---
layout: default
title: Demonstration run
---

# Demonstration run

> **FAKE DATA — FOR TESTING AND DEMONSTRATION ONLY — NOT FOR AGRONOMIC DECISIONS**

This deliberately small run uses fabricated field boundaries, the manual Corn
profile, and a fixed seed. It contains soil-test points with ordinary-kriging
surfaces, planting center and row-unit logs, a variable-rate dry-fertilizer
operation, yield-monitor logs, polygon-grid surfaces, and the branded
single-field split-comparison viewer with a center drag handle.

- [Open the interactive comparison viewer](sample_run/fake_farm_data_review.html)
- [Download the complete demonstration run](fake-farm-data-demo.zip)
- [Inspect the run manifest](sample_run/run_manifest.json)

## Full example dataset

The [full four-field example](https://github.com/noahdfreeman/fake-farm-data-generator/releases/download/v1.0.0/Fake_Farm_Data_Example.zip)
contains four fields, four years, all four generated data types, GeoPackages,
shapefiles, and a portable HTML review. The download is approximately 368 MB
and requires about 8.6 GB of free space when extracted.

The full archive was generated during final V1 development, so its internal
manifest reports the pre-release generator version `0.30.0`. Its data remains
fake and uses the V1 output schema.

The HTML viewer uses bundled Leaflet assets for local data. Online basemap tiles
still require internet access.
