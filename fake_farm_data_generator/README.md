# Fake Farm Data Generator QGIS plugin

This directory is the installable QGIS plugin package.

Version 1.0.1 provides all four individual generators and a selection-first seven-tab complete workflow. The dialog accepts multiple checked boundary layers, explicit data-type choices, ten checkable crop-year buttons, a US Central Time default with an IANA timezone selector, editable field-year crops, and crop-specific planting tabs. It opens from the Processing Toolbox or the branded logo button in the plugin toolbar/menu.

The unit-system selector defaults to Imperial. Metric runs use hectares, meters/centimeters, km/h, seeds/ha, kg/ha, and crop-appropriate t/ha or kg/ha yield units. The complete-run tool supplies converted metric defaults to every child generator; each output feature and manifest records its unit system and explicit measurement units.

GeoPackage remains the canonical internal output. Users may also select ESRI Shapefile, GeoJSON, CSV for point layers, and GeoTIFF for polygon-grid surfaces. Shapefile aliases are recorded in `field_name_map.json`; GeoTIFF names include the rasterized attribute.

Every generated GeoPackage contains a registered `ffdg_run_metadata` attribute table with the fake-data warning, generator/run identity, completion status, master seed, unit system, field count, and manifest reference.

The interactive crop workflow supports:

- An explicit **Pull Crops from USDA CDL** action using the public CroplandCROS ImageServer.
- Bounding-box-only remote requests; field geometry and attributes are not uploaded.
- Combined-area requests when possible to reduce API traffic, with field-sized fallback requests.
- Rotation inference for unavailable selected years, permanently labeled as inferred rather than observed.
- Original CDL class, percentage, source, source year, resolution, lookup time, and override status in planting/yield features and the complete manifest.

Local-CDL, cache, and manual-profile controls are not shown in the complete-run dialog. Their legacy Processing parameters remain available for scripted backward compatibility.

The soil-test generator supports:

- One or multiple selected field polygons.
- First year, interval, and optional final year.
- Regular-grid or deterministic random sample placement.
- The current tool's Low, Medium, and High variability multipliers.
- Phosphorus and potassium in ppm or dedicated fake lb/acre profiles.
- Unattributed point-only output.
- An optional per-field polygon-grid surface using ordinary kriging or IDW.
- Spherical, exponential, and Gaussian kriging variograms with automatic or user-entered range, relative nugget, neighbor limit, variance provenance, and an explicit IDW fallback flag.
- A timestamped run folder and JSON manifest.

The planting generator supports:

- Automatic longest-axis or manual travel bearing.
- Planter-center points by default, individual row-unit points, or both.
- Linked center, pass, and row-unit identifiers.
- Deterministic population, speed, seed spacing, depth, headland, pass, and row-unit variation.
- A clipped polygon grid with selected population, speed, seed-spacing, and seed-depth attributes.
- Crop-specific population bounds, seed depths, and planting dates in nested crop tabs.
- Fake singulation, spacing quality, skips, ride quality, ground contact, furrow moisture and temperature, uniform furrow, and clean furrow metrics in point logs and selectable surfaces.
- Preflight point/cell estimates and an output manifest with actual counts.

The as-applied generator supports:

- Dry fertilizer, liquid fertilizer, lime, chemical spraying, manure, and broadcast seeding.
- Flat-rate settings with small bounded logged variation.
- Variable-rate settings with larger smooth fake spatial variation.
- Equipment passes, timestamps, speed changes, headlands, and a generated fake-terrain effect.
- Point logs and a clipped polygon-grid surface with explicit operation and product provenance.
- An editable complete-run operation table with per-year or All-year rows, duplication, removal, ordering, and multiple operations in the same year.

The yield generator supports:

- The twelve v1 crop profiles with crop-appropriate output units.
- Bounded dry yield, moisture, standard-moisture wet yield, speed, passes, timestamps, and headland penalties.
- Automatic or manual travel bearings.
- Combine-style point logs and a clipped polygon-grid surface.
- Field-wide base yield, smooth gradient, low-frequency waves, bounded point noise, and perpendicular end-row passes adapted from the original yield script.
- Manual or resolved field-year crop provenance on every point and surface feature.

All outputs are labeled:

> FAKE DATA - NOT FOR AGRONOMIC DECISIONS

The portable review includes every soil-test point, a configurable 100 to 200,000 feature limit per high-volume log or polygon-surface layer (20,000 by default), deterministic sampling provenance, field/year/data-type/operation filters, independent left/right data layers and numeric attributes, an always-visible field-boundary background, color ramps and legends, Hybrid/Satellite/Streets basemaps, reset extent, and a compare toggle that defaults off. Leaflet runtime assets are bundled so local generated data remains visible offline; online basemap tiles still require internet access.

Before a complete run begins, the dialog reports selected fields and area plus estimated soil, planting, application, yield, and surface records and a conservative runtime range. The estimate is stored with the saved recipe and final manifest; actual component counts remain separate.

During generation, QGIS reports weighted overall progress across component creation, consolidation, exports, the HTML review, and finalization. Completion reports elapsed time, created record types, the saved folder, and actions to open either the HTML review or output folder. Cancellation is checked between machine passes and major export, consolidation, and review steps. Canceled or failed work retains an `incomplete` manifest and never claims a completed review.

The complete-run dialog also exposes the individual soil placement, nutrient-unit, kriging, planter, row-unit, application, combine, direction, date, variability, and polygon-grid settings. Those settings are validated before execution, used by the point estimator, passed to the child generators, and retained in the run recipe and manifest.

Use **Load recipe…** and **Save recipe…** on the General tab to reuse a configuration. The loader accepts both pre-run dialog recipes and the `run_recipe.json` written by an earlier complete run. Boundary layers are intentionally selected fresh in QGIS; crop years, timezone, generator settings, and the output parent folder are restored.

The General tab can map input columns to field ID, field name, farm name, and grower name. Blank mappings auto-detect conventional names. Every generator carries those values into point and surface records, with `Field_001`, `Field_002`, and similar deterministic fallbacks when identifiers are absent.

Every complete run retains its selected polygons in `fake_field_boundaries.gpkg`. The layer records mapped identities, acres/hectares, and `boundary_source=user_provided`, and is available in the portable comparison viewer and selected derivative formats.

Version 1.0.1 includes incremental weighted progress, runtime estimates and completion actions, permanent background boundaries, compare-off review startup, restored natural yield patterns with end rows, HTTPS-only crop-service requests, and scoped QGIS enums. Complete runs continue to execute in a separate `qgis_process` worker so a worker-level failure cannot terminate desktop QGIS.
