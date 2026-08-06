# Fake Farm Data Generator V1

The first public release of Fake Farm Data Generator provides one QGIS plugin
for creating clearly labeled fake soil-test, planting, as-applied, and yield
datasets.

## Highlights

- Seven-tab complete-run workflow plus four individual Processing algorithms.
- Multi-field and multi-year generation with repeatable random seeds.
- USDA CroplandCROS/CDL crop suggestions and editable crop assignments.
- Soil-test grid or random sampling with Ordinary Kriging and IDW surfaces.
- Planter-center or row-unit planting logs with advanced planter metrics.
- Flat- and variable-rate as-applied operations.
- Natural-looking yield logs with full-perimeter headland passes.
- GeoPackage, Shapefile, GeoJSON, CSV, and GeoTIFF exports.
- Portable HTML review with filtering, opacity, and split comparison.
- Runtime estimates, incremental progress, cancellation, and completion details.

## Release assets

- `fake_farm_data_generator-1.0.1.zip` — install through QGIS **Install from ZIP**.
- `Field_Examples.zip` — three GeoPackage field-boundary inputs for trying the
  plugin without supplying your own boundaries.
- `fake-farm-data-demo.zip` — public two-field example with all four data types
  and the portable HTML review.
- `Fake_Farm_Data_Example.zip` — full four-field, four-year example with all
  four data types and all selected vector formats. Approximately 368 MB to
  download and 8.6 GB when extracted.
- `Fake_Farm_Data_Example.zip.sha256` — checksum for the full example archive.
- `fake_farm_data_generator-1.0.1.zip.sha256` — plugin archive checksum.

> **FAKE DATA — FOR TESTING AND DEMONSTRATION ONLY — NOT FOR AGRONOMIC DECISIONS**

Version 1.0.1 includes the QGIS Plugin Repository security-scan and QGIS 4
compatibility remediation required after the blocked 1.0.0 submission. It also
fixes complete-run startup in a fresh QGIS project whose project CRS has not yet
been initialized; a basemap is not required before loading the example fields.
