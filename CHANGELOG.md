# Changelog

All notable changes to Fake Farm Data Generator are documented here.

## 1.0.0 - 2026-08-05

- Made field switching in the portable review reliable by selecting a field when the user clicks anywhere inside its polygon, in addition to the outline and dropdown controls.
- Fixed isolated-worker startup when more than one output format is selected by serializing QGIS multi-enum values as one comma-separated argument.
- Moved the required parent output-directory selector to the first row of the General page.
- Replaced headland-width inputs with machine-pass counts for planting, as-applied, and yield; planting defaults to two planter passes and yield automatically matches their physical width.
- Added a 150-foot (45.72-meter) default soil-sampling setback from exterior boundaries and polygon holes.
- Rounded review-page area summaries to the nearest tenth of an acre or hectare.
- Raised the always-visible field boundaries above data layers so clicking any boundary reliably selects and zooms to that field.
- Replaced child-algorithm percentage scraping with explicit weighted overall progress, reserving final progress for consolidation, format exports, HTML generation, and manifest completion.
- Added a pre-run estimated runtime range based on requested record types, interpolation/surface workload, selected formats, and HTML review size.
- Added elapsed time, output location, created-record summary, and Open HTML Review/Open Output Folder actions to the completion dialog.
- Removed field boundaries from left/right data-layer selectors and now draw the selected field boundary continuously behind both maps.
- Defaulted portable review comparison mode to off while retaining the left layer full screen.
- Restored the original yield script's field-wide base yield, smooth gradient, three low-frequency waves, bounded point noise, headland penalty, and perpendicular end-row passes.
- Added record-level yield progress updates for large point and surface runs.
- Replaced one-axis end rows with full-perimeter headland passes for planting, as-applied, and yield logs while keeping straight working passes inside the configured headland zone.
- Kept every field boundary visible in the HTML review and made boundary clicks switch and zoom to that field.
- Added a data-opacity slider and defaulted soil, planting, application, and yield layers to pH, population, actual rate, and dry yield respectively.
- Batched high-volume point attribute writes and cached the yield field pattern; the repeatable 35,000-point yield benchmark improved from 4.21 seconds to 2.96 seconds, and preflight duration estimates were recalibrated.

## 0.29.0 - 2026-08-05

- Replaced the toolbar icon with the supplied Fake Farm Data Generator logo and bundled the same logo in every portable review.
- Replaced the bottom comparison range with the county-tool-style vertical divider and circular center handle.
- Kept the left layer full-screen when comparison is disabled and hid the right-layer controls.
- Changed the field filter to require one field at a time and automatically zoom to the selected field.
- Moved Map Options below the Leaflet zoom controls and reformatted the information, statistics, selectors, and responsive layout.
- Removed Run manifest, Run recipe, and Generated files links from the review page.

## 0.28.0 - 2026-08-05

- Added a visible toolbar/menu launcher with a bundled farm-data icon.
- Added General-page selectors for Soil Tests, Planting, As-Applied, and Yield; no data type is selected until the user chooses it.
- Defaulted the timezone dropdown to US Central Time (`America/Chicago`).
- Added crop dropdowns for every field-year with explicit `user_override` provenance.
- Moved complete-run generation into a separate `qgis_process` worker with streamed progress, cancellation, and failure isolation from desktop QGIS.
- Added safe worker shutdown and incomplete-run marking after cancellation or worker failure.

## 0.27.0 - 2026-08-05

- Added checkable multi-layer field-boundary input with selected-feature support and deterministic normalization across source CRSs.
- Replaced typed crop years with ten checkable year buttons, defaulting to the current year, and replaced the timezone field with an IANA timezone selector.
- Simplified the interactive crop workflow to a **Pull Crops from USDA CDL** action and removed visible manual-profile, local-CDL, and cache controls.
- Added explicit rotation-based crop inference for CDL years that are unavailable and preserved `rotation_inference` provenance through planting, yield, recipes, and manifests.
- Changed planting point output to Planter Center by default and added crop-specific population, seed-depth, and planting-date tabs.
- Added fake singulation, spacing quality, skips, ride quality, ground contact, furrow moisture and temperature, uniform-furrow, and clean-furrow metrics to planting output and optional surfaces.

## 0.26.0 - 2026-08-04

- Made **Create Complete Fake Farm Dataset** open the seven-tab builder directly from the QGIS Processing Toolbox.
- Removed user-facing JSON override boxes and hid the internal Processing transport parameters while retaining command-line and model compatibility.
- Added visible first-year, final-year, and interval controls for soil-test scheduling.
- Added an editable per-crop table for dry-yield and moisture ranges, with correct Imperial/Metric conversion.
- Added Processing-preset loading, schedule validation, estimate coverage, recipe round-trip coverage, and live QGIS verification for the new interface.

## 0.25.0 - 2026-08-04

- Added dedicated GitHub Pages documentation for installation, complete and individual workflows, parameters, schemas, crop sources, outputs, review behavior, development, and releases.
- Added prepared cross-platform unit/package CI, official QGIS 3.34/3.40/3.44/4.2 Docker smoke tests, tagged release publishing, Pages deployment, and repository contribution templates.
- Added a prepared GitHub-hosted macOS job that installs the current QGIS application bundle and runs the same complete PyQGIS smoke suite through bundle-aware path discovery.
- Added a release-version verifier and repository documentation/workflow tests.
- Fixed Qt 6 scoped-enum compatibility for QGIS 4 cache paths, table items, cursors, dialog buttons, and message boxes.
- Passed the full plugin smoke test in official Linux QGIS 3.34, 3.40, 3.44, and 4.2 images.
- Added a verified, downloadable all-generator fake demonstration run with an interactive comparison viewer.
- Added the permanent fake-data warning and generator provenance to reusable and generated JSON recipes.
- Removed the obsolete build-stage pending-algorithm module and replaced the demo publishing placeholder with verified demo documentation.

## 0.24.0 - 2026-08-04

- Added consistent progress messages with the current field/component, records created, elapsed time, and estimated remaining time.
- Added cancellation checks between application and yield passes and during derivative export, GeoPackage consolidation, and portable-review serialization.
- Guaranteed that canceled generation retains an `incomplete` manifest and does not claim a completed HTML review.
- Added dependency-free progress tests and live-QGIS cancellation/progress verification.

## 0.23.0 - 2026-08-04

- Added a configurable portable-review limit of 100 to 200,000 features per high-volume layer, with a 20,000-feature default.
- Preserved every soil-test point in the review regardless of the configured limit while deterministically sampling large polygon surfaces and machine-log layers.
- Saved the review limit in reusable dialog recipes, generated run recipes, component manifests, and complete-run manifests.
- Added preflight visibility and live-QGIS verification for the selected limit, soil-point exemption, and deterministic high-volume sampling.

## 0.22.0 - 2026-08-04

- Consolidated complete-run GeoPackage output into one canonical multi-layer `fake_farm_data_<year>.gpkg` for every selected year.
- Merged per-field planting and yield records and per-operation application records into their corresponding yearly layers without changing individual algorithms.
- Updated Shapefile, GeoJSON, CSV, GeoTIFF, and portable HTML generation to enumerate every spatial layer in a multi-layer GeoPackage.
- Retained intermediate component packages as provenance-only sources while excluding them from the public output manifest.
- Added live-QGIS verification of yearly layer registration, merged identities and operations, component-source provenance, exported derivatives, and viewer data.

## 0.21.0 - 2026-08-04

- Added a true two-stage complete-run workflow: validate and populate a detailed preflight review page, then explicitly run the reviewed configuration.
- The review page lists field scope, acreage, years, data types, expanded application operations, timezone, crop-review and network status, every point/surface estimate, formats, destination, and qualitative runtime warnings.
- Added dependency-free and live-QGIS coverage for preflight-review contents and navigation.

## 0.20.0 - 2026-08-04

- Added a visible CDL cache directory setting to the Years and Crops tab.
- Added a safe cache-clear control that deletes only plugin-owned `cdl_*.tif` and `cdl_*.json` files after confirmation.
- Passed the configured cache into crop suggestions and complete runs, and retained it in reusable and generated recipes plus manifests.
- Added dependency-free cache-cleanup coverage and live-QGIS recipe/manifest verification.

## 0.19.0 - 2026-08-04

- Guaranteed that every soil-test point is included in the portable HTML review, regardless of the general high-volume point limit.
- Added explicit `review_sampling` provenance to every serialized review layer.
- Added safe, local links to generated output files in the review's run-information panel.
- Added live-QGIS checks for complete soil-point inclusion and generated-file links.

## 0.18.0 - 2026-08-04

- Added an optional common machine-timestamp timezone setting to the complete-run dialog and Processing algorithm.
- Added optional timezone parameters and a `timezone` field to planting, as-applied, and yield point logs.
- Carried the timezone through complete-run recipes, manifests, child manifests, and application-operation JSON, including per-operation overrides.
- Added dependency-free validation plus live QGIS verification of standalone, complete-run, and recipe round-trip timezone provenance.

## 0.17.0 - 2026-08-04

- Added `fake_field_boundaries.gpkg` to every complete run.
- Added mapped field/farm/grower identities, acres, hectares, fake-data labeling, and `boundary_source=user_provided` to each retained boundary.
- Used normalized boundaries as the multi-field input to soil and application child generators so explicit identity mappings reach every output type.
- Included field boundaries in Shapefile/GeoJSON derivatives and the portable comparison review.
- Added complete-run manifest counts and live-QGIS verification for boundary count, mapped IDs, downstream soil IDs, and viewer inclusion.

## 0.16.0 - 2026-08-04

- Added a registered, attribute-only `ffdg_run_metadata` table to every generated GeoPackage.
- Embedded the fake-data warning, generator version, run ID, completion status, creation time, master seed, unit system, field count, and manifest filename.
- Added explicit SQLite connection closing to keep Windows output and complete-run temporary folders releasable.
- Added dependency-free table/registration tests and live-QGIS GeoPackage verification.

## 0.15.0 - 2026-08-04

- Added General-tab selectors for field ID, field name, farm name, and grower name input columns.
- Added equivalent optional Processing parameters to the complete-run algorithm.
- Added conventional-column auto-detection and deterministic fallbacks for individual generators.
- Preserved source attributes when the complete orchestrator creates one-field child layers.
- Added duplicate mapped-field-ID validation and recorded mappings/resolved identities in recipes and manifests.
- Displayed mapped field IDs in the crop review table while retaining stable internal field-year override keys.
- Added field mapping to reusable and generated recipe round trips.

## 0.14.0 - 2026-08-04

- Added General-tab controls to save the current complete-run configuration as a reusable JSON recipe.
- Added recipe loading with unit-aware restoration of all soil, planting, application, yield, crop, format, seed, year, and output-directory settings.
- Added compatibility for loading the `run_recipe.json` emitted by an earlier completed run.
- Added recipe type/version markers and retained the local CDL path in generated run recipes.
- Added live-QGIS round-trip coverage for both pre-run dialog recipes and generated run recipes.

## 0.13.0 - 2026-08-04

- Added full soil controls to the complete-run dialog, including regular-grid/random placement, current-tool variability, ppm or rate-basis P/K units, unattributed mode, IDW, and ordinary kriging parameters.
- Added full planting machine, row-unit, population, logging, direction, date, variability, and surface controls to the complete-run dialog.
- Added full yield machine, logging, direction, date, headland, variability, and surface controls to the complete-run dialog.
- Routed normalized advanced settings through the orchestrator into child generators and retained them in recipes and manifests.
- Updated preflight estimates to use the configured soil density, row count, machine widths, logging intervals, and surface grids.
- Added a field-by-year crop review table showing CDL class, dominance, source, status, suggested crop, and an editable reviewed crop.
- Split crop suggestion from strict review enforcement so the GUI can display low-confidence and failed lookups without guessing a crop, while Processing remains strict.

## 0.12.0 - 2026-08-04

- Added an editable complete-run application table with add, duplicate, remove, reorder, per-year/All targeting, and multiple same-year operations.
- Added dependency-free validation and deterministic child seeds for application operations.
- Added portable-review filters for field, year, data type, and operation.
- Added independent left/right numeric attribute styling, selectable color ramps, computed legends, three basemap choices, reset extent, and a compare toggle.
- Bundled Leaflet 1.9.4 runtime assets and license for offline local-layer display.
- Added complete-run field count and area metadata and enforced the 5,000-acre limit.
- Added a complete-run preflight record estimate to the confirmation, recipe, and manifest.

## 0.11.0 - 2026-08-04

- Added the seven-tab custom complete-run dialog and QGIS menu/toolbar action.

## 0.10.0 - 2026-08-04

- Added selectable Shapefile, GeoJSON, point CSV, and surface GeoTIFF derivatives.

## 0.9.0 - 2026-08-04

- Added shared Imperial and Metric generation and explicit units.

## 0.8.0 - 2026-08-04

- Added cache/local/USDA CDL crop resolution, the 40% review rule, overrides, and provenance.

## 0.7.0 - 2026-08-04

- Added portable HTML reviews and split comparison.

## 0.6.0 - 2026-08-04

- Added complete-run orchestration.

## 0.5.0 - 2026-08-04

- Added yield generation.

## 0.4.0 - 2026-08-04

- Added as-applied generation.

## 0.3.0 - 2026-08-04

- Added planting generation.

## 0.2.0 - 2026-08-04

- Added soil-test ordinary kriging and IDW surfaces.
