# Fake Farm Data Generator

## Version 1.0 Product and Technical Specification

| Item | Value |
| --- | --- |
| Document status | Initial implementation specification |
| Product name | Fake Farm Data Generator |
| Target release | v1.0.0 |
| Plugin type | QGIS Processing provider with a custom complete-run dialog |
| License | GPL-3.0-or-later |
| Maintainer | Noah Freeman |
| Supported QGIS versions | QGIS 3.28 through current QGIS 3.x, with QGIS 4.x compatibility |
| Supported operating systems | Windows, macOS, and Linux |
| Primary units | Imperial by default; metric selectable |

## 1. Purpose

Fake Farm Data Generator is an open-source QGIS plugin for creating clearly identified fake precision-agriculture datasets inside one or more field polygons. It is intended for software development, demonstrations, training, screenshots, workflow testing, and other situations where real grower data should not be used.

Version 1 must create four data types:

1. Soil-test points and interpolated polygon-grid surfaces.
2. Planting log points and polygon-grid surfaces.
3. As-applied log points and polygon-grid surfaces.
4. Yield-monitor points and polygon-grid surfaces.

Users may create any subset of these data types in one complete run or run each generator independently from the QGIS Processing Toolbox. A complete run may cover multiple fields and multiple years.

The word **fake** is intentional. The product must not describe generated agronomic records as observed, measured, predicted, modeled, or synthetic field truth. The generated values may be plausible enough to exercise agricultural software, but they must not be driven by actual soils, elevation, weather, yield history, or other external agronomic layers.

The only optional real-world classification in v1 is the crop identity suggested from the USDA Cropland Data Layer. Crop identification is metadata used to choose a fake crop profile; it does not make the generated records real.

## 2. Goals

Version 1 must:

- Install as one standard QGIS plugin ZIP.
- Expose one complete-dataset tool and four individual data generators.
- Accept one or multiple checked polygon layers and selected features within each layer.
- Generate up to 20 fields, 5,000 total acres, and 10 crop years in one run.
- Allow the user to choose which data types and output formats to create.
- Support repeatable output through a master random seed.
- Support imperial and metric configurations from a top-level toggle.
- Pull historical crops from the USDA Cropland Data Layer API and infer unavailable years from crop rotation with explicit provenance.
- Save and reload complete-run configurations as JSON recipes.
- Generate a portable HTML review for every run.
- Provide independent left and right map selectors with a draggable comparison divider.
- Publish documentation and a demonstration through GitHub Pages.
- Mark every generated artifact unambiguously as fake data.
- Run without paid APIs, proprietary Python packages, or required third-party accounts.

## 3. Non-goals for v1

Version 1 will not:

- Predict agronomic outcomes.
- Correlate soil tests, planting, applications, or yield with each other.
- Use actual soil, terrain, weather, management, or remote-sensing values to generate records.
- Claim machinery-vendor compatibility.
- Export ISOXML, AgGateway ADAPT, or proprietary monitor file formats.
- Reproduce a specific planter, applicator, combine, lab, or monitor implementation exactly.
- Generate prescription recommendations.
- Support more than 20 selected fields, 5,000 acres, or 10 years in one run.
- Upload field polygon geometry to a remote service.
- Require Google Earth Engine, an ArcGIS account, or an API key.

## 4. User-facing tools

The plugin Processing provider will be named **Fake Farm Data Generator** and expose five algorithms. The complete workflow is also launched by a bundled-icon button in the QGIS plugin toolbar and menu.

### 4.1 Create Complete Fake Farm Dataset

This is the primary user workflow. It opens a custom tabbed configuration dialog and calls the same internal generators used by the individual algorithms.

Tabs:

1. **General** — input polygons, selected-feature behavior, field identifiers, unit system, years, master seed, output folder, and saved recipe.
2. **Crops** — on-demand USDA CDL API lookup, crop confidence, and rotation-inferred missing years.
3. **Soil Tests** — sampling schedule, grid or random placement, density, depth, nutrient units, fertility range, variability, interpolated surfaces, and unattributed point-only mode.
4. **Planting** — planter geometry, output point types, population, speed, logging interval, direction, headlands, date, and surface settings.
5. **Applications** — editable operation table and shared applicator settings.
6. **Yield** — crop profiles, yield range, moisture, equipment, speed, logging interval, direction, headlands, date, and surface settings.
7. **Outputs and Review** — formats, layer selection, HTML review options, symbology, and point-count estimate.

The user must be able to move backward and forward without losing settings. Before execution, the dialog shows a review page containing selected fields, acreage, years, data types, estimated point counts, output formats, network requirements, warnings, and destination.

### 4.2 Create Fake Soil Test Data

Runs the soil-test generator for one or multiple fields and a configured sampling schedule.

### 4.3 Create Fake Planting Data

Runs the planting generator for one or multiple fields and crop years.

### 4.4 Create Fake As-Applied Data

Runs one or more configured application operations for one or multiple fields and years.

### 4.5 Create Fake Yield Data

Runs the yield generator for one or multiple fields and crop years.

The four individual algorithms must remain usable through the Processing Toolbox, `qgis_process`, Processing models, and Python. The custom complete-run dialog is an orchestrator, not a separate generation implementation.

## 5. Input field behavior

### 5.1 Accepted input

- One or more valid QGIS polygon or multipolygon vector layers.
- One or multiple polygon features.
- Any source CRS that QGIS can transform.
- Polygon holes are respected.
- Empty or invalid geometry is reported by feature; recoverable geometry may be repaired using standard QGIS geometry tools.

### 5.2 Feature selection

- Every checked layer is included in one normalized temporary run layer.
- Within each checked layer, selected polygon features take precedence; otherwise all features in that layer are processed.
- The tool must not silently process unselected features when a selection exists.

### 5.3 Field identity

The user may map input columns for grower, farm, and field identifiers. Missing values are generated deterministically:

- `grower_name`: optional blank value.
- `farm_name`: optional blank value.
- `field_id`: `Field_001`, `Field_002`, and so on.
- `field_name`: defaults to the generated `field_id`.

All output records include `field_id`. Fields are combined into data-type/year layers instead of producing a separate layer for every field.

### 5.4 Size limits

The complete-run validator enforces:

- Maximum 20 field features.
- Maximum 5,000 total acres, or 2,023.43 hectares.
- Maximum 10 selected crop years.

The tool reports which limit was exceeded and does not partially begin an invalid run.

## 6. Common run configuration

### 6.1 Years

The complete dialog displays checkable buttons for the current year and previous nine years, with the current year selected initially. Users may select any combination; no complete run may contain more than 10 years.

The General page provides separate Soil Tests, Planting, As-Applied, and Yield checkboxes. No data type is selected initially, preventing an accidental all-data run.

Planting and yield require one reviewed crop assignment for every field-year. Applications may be configured for any selected year. Soil-test years are derived from the separate soil sampling schedule.

### 6.2 Unit system

An **Imperial / Metric** toggle appears at the top of the complete-run dialog and defaults to Imperial.

Imperial defaults include acres, feet, inches, miles per hour, bushels per acre where applicable, pounds per acre, tons per acre, gallons per acre, fluid ounces per acre, and seeds per acre.

Metric defaults include hectares, meters, centimeters, kilometers per hour, tonnes per hectare or kilograms per hectare where applicable, liters per hectare, and seeds per hectare.

Changing the toggle converts displayed numeric settings rather than reinterpreting unchanged numbers. Output records contain both a value and an explicit unit field where the measurement is not self-describing. Internal geometry calculations use meters in a suitable projected CRS.

### 6.3 Random seed

- `0` requests a new random master seed.
- A positive integer reproduces a run.
- The resolved master seed is stored in the manifest and every output layer.
- Stable child seeds are derived from the master seed, field ID, year, data type, and operation ID.
- Adding or removing one requested data type must not change values in otherwise identical generated layers.

### 6.4 Dates and timestamps

Editable default operation dates are:

| Operation | Default date | Default random window |
| --- | --- | --- |
| Preplant application | April 15 | plus or minus 14 days |
| Planting | May 1 | plus or minus 14 days |
| In-season application | June 15 | plus or minus 14 days |
| Harvest | October 15 | plus or minus 14 days |
| Fall application | November 1 | plus or minus 14 days |
| Soil sampling | November 10 | plus or minus 14 days |

The user sets or accepts a default month and day. Each year receives deterministic random variation within the configured window. Timestamps advance along passes using speed and logging interval. All timestamp strings use ISO 8601 local date/time format and include a separate timezone field. The IANA timezone dropdown defaults to US Central Time (`America/Chicago`).

### 6.5 Travel direction

Planting, application, and harvest support:

- **Automatic:** derive the main pass bearing from the field's longest oriented axis.
- **Manual:** user-supplied bearing from 0 through less than 360 degrees.

The selected bearing may receive a small, deterministic per-year variation when enabled. The exact bearing used is stored in every affected layer's metadata.

## 7. Crop determination

### 7.1 Interactive source

The complete dialog uses the public USDA CroplandCROS ArcGIS REST image service through an explicit **Pull Crops from USDA CDL** button. It does not expose local-CDL, cache, or manual-profile controls. Legacy Processing parameters remain available only for backward-compatible scripted workflows.

The initial CroplandCROS service endpoint is:

`https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer`

The endpoint must be isolated behind a crop-source adapter so it can be updated without changing generator code. CropScape, Google Earth Engine, and Esri Living Atlas are not default v1 dependencies.

### 7.2 Privacy and request handling

- Remote requests use a bounding rectangle in the service's supported coordinate system.
- Field polygon geometry and attributes are not uploaded.
- The interactive workflow uses temporary downloaded subsets and removes them when the lookup finishes; it does not expose or depend on a persistent local CDL cache.
- One combined-area request per year is attempted before field-sized fallbacks to reduce API calls.
- Network failure never invents a crop assignment when no usable observed year exists for rotation inference.
- Local CDL rasters, cache paths, and manual crop-profile controls are not shown in the complete-run interface.

### 7.3 Field-year classification

For each field-year, the tool calculates a categorical histogram inside the polygon and ignores background and nonagricultural classes when identifying the dominant agricultural crop.

- A supported dominant agricultural class is displayed with its agricultural-pixel percentage.
- Selected years unavailable from the API are estimated from nearby API years and labeled `rotation_inference`.
- The run is blocked only when neither API observations nor a rotation estimate can resolve a field-year.
- The crop table shows every API observation and rotation-inferred result before generation.
- Every crop cell is a dropdown. A user change is stored as `crop_source = user_override` while retaining available CDL provenance fields.

Each output stores:

- `crop_name`
- `crop_code`
- `crop_pct`
- `crop_source` (`croplandcros` or `rotation_inference` in the complete workflow)
- `crop_source_year`
- `crop_resolution`
- `crop_lookup_at`
- `crop_overridden` (`false` in the complete workflow; retained for schema compatibility)

### 7.4 Built-in v1 crop profiles

V1 includes configurable fake-data profiles for:

- Corn
- Soybeans
- Wheat
- Cotton
- Grain sorghum
- Barley
- Oats
- Canola
- Dry beans
- Sunflowers
- Alfalfa
- Other Crop

Wheat-related CDL classes may map to a wheat profile while retaining the original CDL code and name. Unsupported observations are not silently relabeled. If another usable API year exists, the missing assignment may be rotation-inferred; otherwise the run is blocked with the unresolved field-year identified. Other Crop retains configurable yield and planting defaults.

## 8. Fake variation model

Every generator creates independent fake variation. No generated data type influences another.

Permitted fake effects include:

- Low-frequency waves.
- Smooth gradients.
- Bounded point noise.
- Edge or headland effects.
- Pass-to-pass offsets.
- Speed changes.
- A generated smooth `fake_terrain_effect` surface.

The fake terrain effect is not derived from a DEM and must never be labeled elevation, slope, or measured terrain. It may influence simulated speed and application-rate variation. The run manifest explicitly states that no external terrain layer was used.

Users select Low, Medium, or High variability, with advanced numeric controls available in each generator. Values are clamped to configured minimum and maximum bounds.

## 9. Soil-test generator

### 9.1 Schedule

The user specifies:

- First sampling year.
- Sampling interval in years.
- Optional final sampling year.

The default interval is three years. Only derived years within the complete run's configured range are created.

### 9.2 Parameters

- Acres or hectares per sample point.
- Point placement: Regular Grid or Random.
- Boundary setback; 150 feet by default in Imperial mode and 45.72 meters in Metric mode.
- Sample depth.
- Lab name.
- Fertility level: Low, Medium, or High.
- Variability level: Low, Medium, or High.
- Phosphorus and potassium units: ppm or lb/acre.
- Base sampling date and random date window.
- Optional unattributed mode that creates locations without nutrient columns.
- Regular-grid rotation and offset when Regular Grid is selected.
- Surface grid-cell size and interpolation method: Ordinary Kriging or IDW.
- Kriging variogram model, practical range, relative nugget, and maximum neighbors.
- IDW power and maximum neighbors.
- Nutrients to include in the interpolated polygon-grid surface.

The current 2.5-acre regular-grid behavior is retained as the imperial default. Regular Grid uses density-derived spacing, optional rotation, and optional offset. Random creates the density-derived target number of deterministic random points inside each field. Both modes use a projected CRS, preserve polygon holes, remain outside the configured setback from exterior boundaries and polygon holes, and reproduce the same locations for the same child seed. A field too narrow for the requested setback stops with an actionable field-specific error.

The soil variability selector must preserve the current tool's behavior:

| Variability | Standard-deviation multiplier | Meaning |
| --- | ---: | --- |
| Low | 0.5 | Tight clustering around each field's base values |
| Medium | 1.5 | Normal spread around each field's base values |
| High | 3.0 | Wide spread around each field's base values |

Each field first receives deterministic base nutrient values from the selected fertility profile. Each point then receives bounded spatial noise around those field base values using the selected multiplier. The selected variability level and multiplier are stored in the point and surface metadata.

### 9.3 Attributed output

The initial nutrient set is:

- Phosphorus (`P`)
- Potassium (`K`)
- Soil pH (`pH`)
- Buffer pH (`bpH`)
- Organic matter (`OM`)
- Cation exchange capacity (`CEC`)
- Calcium (`Ca`)
- Magnesium (`Mg`)
- Boron (`B`)
- Copper (`Cu`)
- Iron (`Fe`)
- Manganese (`Mn`)
- Zinc (`Zn`)

Ranges are configurable fake-value profiles derived initially from the existing soil-test script. Unattributed mode omits nutrient columns entirely rather than populating them with null values.

The user selects the output units independently for phosphorus and potassium:

| Nutrient | Supported units |
| --- | --- |
| Phosphorus | ppm or lb/acre |
| Potassium | ppm or lb/acre |
| Calcium, magnesium, boron, copper, iron, manganese, and zinc | ppm |
| Organic matter | percent |
| Cation exchange capacity | meq/100 g |
| Soil pH and buffer pH | unitless |

Because these are fake values, selecting lb/acre uses a dedicated bounded fake-value profile in lb/acre rather than claiming a laboratory conversion from ppm. Every nutrient value is accompanied by an explicit unit in layer metadata and the HTML review.

### 9.4 Soil schema additions

In addition to the common fields in Section 13, soil points include:

- `sample_id`
- `sample_date`
- `sample_depth`
- `lab_name`
- `sample_density`
- `density_unit`
- `boundary_setback`
- `distance_unit`
- `fertility_level`
- `variability_level`
- `variability_multiplier`
- `placement_mode`
- `p_unit`
- `k_unit`
- `latitude`
- `longitude`
- Nutrient fields when attributed mode is enabled

All soil-test points are included in the HTML review because their volume is expected to be low.

### 9.5 Soil-test polygon-grid surface

Attributed soil-test runs may create an interpolated polygon-grid surface. The surface is enabled by default; unattributed point-only mode cannot create it.

- A regular polygon grid is built independently for each field and clipped to the field boundary.
- Each cell receives interpolated values at its centroid from that field's fake soil-test points.
- Ordinary Kriging is the default; deterministic IDW remains selectable for compatibility and comparison.
- Ordinary Kriging supports spherical, exponential, and Gaussian theoretical variograms, configurable maximum neighbors, a relative nugget from 0 through 1, and a practical range in feet or meters.
- A kriging range of `0` selects an automatic practical range equal to three times the density-derived sample spacing. The resolved range and whether it was automatic or user-entered are stored in the manifest and surface.
- The normalized theoretical variogram is a fake-data generation setting; the plugin does not fit an empirical variogram or claim that the model represents measured spatial structure.
- A singular local kriging system falls back to IDW for that cell, sets `kriging_fallback = true`, and increments the manifest fallback count. It must never fail silently.
- No points from another field may influence a cell.
- Cells outside a field or inside a polygon hole are excluded.
- The user selects which nutrients to include; the default is all generated nutrients.
- One surface layer contains the selected nutrient columns so the viewer can switch the displayed attribute without duplicating geometry.
- Interpolated nutrient values are clamped to their configured fake profile ranges so kriging overshoot cannot create values outside the requested profile.

Surface fields include the common metadata plus:

- `cell_id`
- `grid_size`
- `distance_unit`
- `surface_method` = `Ordinary Kriging` or `IDW`
- `idw_power`
- `max_neighbors`
- `variogram_model`
- `kriging_range`
- `range_mode`
- `nugget_ratio`
- `kriging_variance`
- `kriging_fallback`
- `source_points`
- `placement_mode`
- `variability_level`
- `variability_multiplier`
- `p_unit`
- `k_unit`
- Selected interpolated nutrient fields

## 10. Planting generator

### 10.1 Outputs

The user may create:

- Planter-center log points, selected by default.
- Individual row-unit log points.
- Both point types.
- One or more polygon-grid planting surfaces.

### 10.2 Parameters

- Crop and year.
- Planter width.
- Number of row units.
- Row spacing.
- Target population.
- Population minimum and maximum.
- Nominal seed depth.
- Nominal speed.
- Logging interval.
- Headland passes; two planter passes by default.
- Automatic or manual travel direction.
- Base planting date and date window.
- Low, Medium, or High variation.
- Surface grid-cell size.
- Surface attributes to create.

Imperial starting defaults are 16 rows and 30-inch spacing. The UI validates that row count multiplied by row spacing is reasonably consistent with planter width and asks the user to resolve large inconsistencies.

### 10.3 Point construction

Center passes are spaced by planter width and clipped to the field. Logged center points are placed from nominal speed and logging interval. Row-unit points are offset perpendicular to the pass bearing by the configured row positions and clipped to the field. The headland zone and full-perimeter passes are derived from the selected number of planter passes multiplied by planter width.

Each row-unit record links to a center record through `center_point_id`, `pass_id`, and `row_unit`. Section state may vary at field edges so outer row units may be inactive while the planter center remains inside the field.

Row-unit locations whose offsets fall outside the field or into polygon holes are not written as active points. The manifest counts these skipped inactive row positions so edge shutoff behavior is explicit without placing output geometry outside the selected field.

### 10.4 Planting values

Planting variation is generated independently from other data. It may include smooth spatial effects, pass offsets, row-unit offsets, speed variation, headland effects, and point noise. No soil test, yield, terrain, or weather input is used.

Planting point fields include:

- `planting_id`
- `center_point_id`
- `record_type` (`planter_center` or `row_unit`)
- `pass_id`
- `row_unit`
- `section_on`
- `timestamp`
- `heading`
- `speed`
- `speed_unit`
- `population`
- `population_unit`
- `seed_spacing`
- `seed_spacing_unit`
- `seed_depth`
- `depth_unit`
- `singulation_pct`
- `spacing_quality_pct`
- `skips_pct`
- `ride_quality_pct`
- `ground_contact_pct`
- `furrow_moisture_pct`
- `furrow_temperature`
- `temperature_unit`
- `uniform_furrow_pct`
- `clean_furrow_pct`
- `row_spacing`
- `planter_width`
- `distance_unit`
- `is_headland`
- `latitude`
- `longitude`

### 10.5 Planting surfaces

The canonical surface is a polygon grid clipped to each field. The user may create surfaces for population, speed, seed spacing, seed depth, and the advanced planter-quality/furrow metrics. Each cell summarizes intersecting generated points; cells without a point use the same fake spatial function evaluated at the cell centroid and are marked with `surface_method = generated_centroid`.

## 11. As-applied generator

### 11.1 Supported operations

V1 supports:

- Dry fertilizer
- Liquid fertilizer
- Lime
- Chemical spraying
- Manure
- Seeding or broadcast-seeding applications

### 11.2 Operation table

The custom dialog provides an editable table with:

- Enabled
- Year
- Operation ID
- Operation type
- Product name
- Flat or variable rate
- Target rate
- Minimum and maximum rate
- Rate unit
- Base date
- Random date window
- Equipment width
- Nominal speed
- Logging interval
- Headland passes
- Automatic or manual direction
- Surface grid size

Users may add, duplicate, remove, and reorder operations. Multiple operations of the same or different type may run in one year.

### 11.3 Rate behavior

**Flat rate** means a single target setting, not perfectly identical logged values. Logged rate still receives bounded variation caused by fake speed changes, headlands, pass changes, rate-control lag, point noise, and the generated fake terrain effect.

**Variable rate** adds a larger smooth spatial target-rate pattern within configured minimum and maximum values. It is not derived from a prescription, soil test, yield map, or real terrain.

### 11.4 As-applied outputs

Each operation produces machine-center log points and a polygon-grid surface. Related operations for a year are stored as one point layer and one surface layer where the output format supports multiple records, differentiated by `operation_id` and `operation_type`.

Point fields include:

- `application_id`
- `operation_id`
- `operation_type`
- `product_name`
- `rate_mode`
- `target_rate`
- `actual_rate`
- `rate_unit`
- `pass_id`
- `timestamp`
- `heading`
- `speed`
- `speed_unit`
- `equipment_width`
- `distance_unit`
- `section_on`
- `is_headland`
- `fake_terrain_effect`
- `latitude`
- `longitude`

Surface cells summarize `actual_rate`, speed, and fake terrain effect.

## 12. Yield generator

### 12.1 Outputs

- Combine-style point logs.
- Polygon-grid yield surface.

### 12.2 Parameters

- Reviewed crop profile and year.
- Minimum and maximum dry yield.
- Moisture range and standard moisture.
- Header or swath width.
- Nominal harvest speed.
- Logging interval.
- Headland passes and yield penalty. The default pass count is calculated to match the physical width of two default planter passes.
- Automatic or manual travel direction.
- Base harvest date and date window.
- Low, Medium, or High variability.
- Surface grid-cell size.

Existing fake yield generation is the starting implementation: passes, along-pass points, smooth bounded variation, moisture, wet and dry yield, headland effects, and a clipped polygon grid. V1 refactors it into reusable, deterministic, multi-field and multi-year code.

The implementation retains the original tool's natural-looking fake pattern: one field-wide base yield, a smooth gradient, three low-frequency spatial waves, bounded point noise, and a configurable headland penalty. Main combine passes stop before the end-row zone and curved machine-center passes follow the complete field perimeter. Planting and as-applied logs use the same full-perimeter headland construction. In the complete-run dialog, the yield pass count updates from the planting headland's physical width and the active planter/combine widths so the operations cover the same headland zone.

### 12.3 Yield point fields

- `yield_id`
- `pass_id`
- `timestamp`
- `heading`
- `dry_yield`
- `wet_yield`
- `yield_unit`
- `moisture_pct`
- `speed`
- `speed_unit`
- `swath_width`
- `distance_unit`
- `logging_interval_sec`
- `is_headland`
- `latitude`
- `longitude`

### 12.4 Yield surface

The canonical surface is a polygon grid clipped to each field. Cells contain dry yield, wet yield, moisture, headland state, grid size, and the number of source points used. The same deterministic fake function may fill a cell with no intersecting point, and the method is recorded.

## 13. Common metadata and fake-data labeling

Every feature layer contains these fields where the output format permits:

- `fake_data` = `true`
- `fake_warning` = `FAKE DATA - NOT FOR AGRONOMIC DECISIONS`
- `generator_name` = `Fake Farm Data Generator`
- `generator_version`
- `run_id`
- `created_at`
- `master_seed`
- `child_seed`
- `unit_system`
- `data_type`
- `field_id`
- `field_name`
- `farm_name`
- `grower_name`
- `crop_year`
- Crop provenance fields from Section 7.3 where applicable

GeoPackage outputs also store run-level metadata in a `ffdg_run_metadata` table. Formats that cannot store a table receive a sidecar metadata JSON file.

File and layer names begin with `fake_` and include data type and year. The HTML review, manifest, README, and exported metadata repeat the fake-data warning. The product must never provide a switch that removes these identifiers.

## 14. Point-count estimation and progress

Before running, the tool estimates records for every selected field, year, and data type using field area, equipment width, row count, nominal speed, logging interval, soil sampling density, and operation count.

The review page displays:

- Estimated soil points.
- Estimated soil surface cells.
- Estimated planter-center points.
- Estimated planting row-unit points.
- Estimated application points.
- Estimated yield points.
- Estimated surface cells.
- Estimated total records.
- A qualitative runtime and storage warning.
- A conservative estimated runtime range based on requested record types, interpolation/surface workload, selected formats, and review size.

Large runs display: **This run may take a while. QGIS must remain open until processing finishes.** The estimator does not silently change resolution. Actual counts are written to the manifest and compared with estimates after completion.

Complete-run generation executes in an isolated `qgis_process` worker so a native worker fault cannot terminate desktop QGIS. A modal progress dialog uses weighted overall progress for generation components, consolidation, derivative exports, HTML review creation, and manifest finalization. It also streams the current data type, year, field, operation, records created, elapsed time, and estimated remaining work while leaving the desktop event loop responsive. Completion reports actual elapsed time, output location, created record categories, and actions to open the HTML review or output folder. The user can cancel the worker. A canceled or failed run writes or is post-marked `status: incomplete` and does not claim success.

## 15. Output formats and folder structure

### 15.1 Selectable formats

V1 supports:

- GeoPackage
- ESRI Shapefile
- GeoJSON
- CSV for point records
- Optional GeoTIFF representations of selected surfaces

The canonical surface remains a polygon grid. A selected GeoTIFF is a rasterized derivative and does not replace the polygon-grid output.

GeoPackage is selected by default and is the reference output. The UI explains format limitations. CSV contains longitude and latitude plus attributes but no polygon surfaces. Shapefile uses deterministic ten-character field aliases documented in a sidecar `field_name_map.json`.

### 15.2 Run folder

One complete run creates:

```text
Fake_Farm_Data_<timestamp>/
  README_FAKE_DATA.txt
  run_manifest.json
  run_recipe.json
  field_name_map.json
  fake_farm_data_review.html
  fake_farm_data_review_data/
  <year>/
    fake_farm_data_<year>.gpkg
    shapefile/                 # when selected
    geojson/                   # when selected
    csv/                       # when selected
    geotiff/                   # when selected
```

Each yearly GeoPackage may contain:

- `fake_field_boundaries`
- `fake_soil_tests_<year>` when scheduled
- `fake_soil_surface_<year>` when scheduled and enabled
- `fake_planting_center_<year>`
- `fake_planting_rows_<year>`
- `fake_planting_surface_<attribute>_<year>`
- `fake_applications_<year>`
- `fake_application_surfaces_<year>`
- `fake_yield_points_<year>`
- `fake_yield_surface_<year>`
- `ffdg_run_metadata`

Individual algorithms use the same naming, metadata, format, and manifest rules.

## 16. Portable HTML review

Every successful run creates `fake_farm_data_review.html` and a companion `fake_farm_data_review_data` folder. They must remain together.

### 16.1 Map behavior

- Leaflet-based map following the Field Boundary Tools local-review pattern.
- Hybrid, Satellite, and Streets basemap choices.
- Independent left and right layer selectors while comparison is enabled.
- All field boundaries always draw behind generated data and are not choices in the left/right data-layer selectors. Clicking another boundary switches the active field and zooms to it.
- County-tool-style vertical divider with a circular center handle.
- **Compare layers** is off initially. When disabled, the left layer fills the map and the right selector and divider are hidden.
- Reset extent control.
- Collapsible map options and run-information panels.
- A single-field selector that filters every generated-data layer to one field and zooms to that field while leaving all boundary outlines visible.
- A data-opacity slider that changes the opacity of the selected generated layers without fading field boundaries.
- Filters for year, data type, operation, and displayed attribute.
- Attribute-specific legends and selectable color ramps. The initial attributes are pH for soil tests, population for planting, actual rate for applications, and dry yield for yield layers when those fields are available.
- Popups with key values, units, field, year, operation, crop provenance, and fake-data warning.
- Summary cards for fields, acres, years, records, and selected-layer statistics.
- The supplied Fake Farm Data Generator logo in a formatted information panel.

Any generated data layer may be compared with any other generated data layer, including different data types or years; field boundaries remain a shared background reference.

### 16.2 Browser-size controls

- All soil-test points are included.
- All soil-test polygon-grid surfaces are available for nutrient-by-nutrient display and comparison.
- Full polygon-grid surfaces are included within a configurable review-size limit.
- Planting, application, and yield points are deterministically sampled for browser display when necessary.
- Sampling affects only the review, never exported data.
- The UI reports displayed points and total raw points.
- Review geometry may be simplified for display, while raw output geometry remains unchanged.

Local vectors are serialized as JavaScript data files so the review works through `file://` without a local web server. Leaflet libraries and online basemaps require internet access. Failure to load a basemap does not prevent local generated layers from displaying if required JavaScript assets are bundled.

### 16.3 Required warning

A persistent, high-contrast banner states:

> FAKE DATA — FOR TESTING AND DEMONSTRATION ONLY — NOT FOR AGRONOMIC DECISIONS

The banner cannot be dismissed permanently. Export/download links repeat the warning.

## 17. GitHub documentation and demo site

The future GitHub repository will include a GitHub Pages site that documents:

- What the plugin creates.
- Installation from the release ZIP.
- Complete-run and individual-tool workflows.
- Parameter and schema references.
- Supported QGIS versions and operating systems.
- Crop-source behavior and offline fallback.
- Output formats and limitations.
- Fake-data warning and appropriate uses.
- A small downloadable demonstration run.
- An embedded or linked demonstration of the split-screen review.
- Changelog, contributing instructions, license, issues, and latest release.

The public repository is <https://github.com/noahdfreeman/fake-farm-data-generator>.

## 18. Proposed source layout

```text
fake-farm-data-generator/
  fake_farm_data_generator/
    __init__.py
    metadata.txt
    plugin.py
    provider.py
    complete_dialog.py
    algorithms/
      complete_dataset.py
      soil_tests.py
      planting.py
      applications.py
      yield_data.py
    core/
      config.py
      validation.py
      fields.py
      crs.py
      seeds.py
      dates.py
      passes.py
      fake_variation.py
      point_estimator.py
      manifest.py
    crops/
      cdl_classes.py
      profiles.py
      resolver.py
      cache.py
      sources/
        local_cdl.py
        croplandcros.py
    exporters/
      geopackage.py
      shapefile.py
      geojson.py
      csv_points.py
      geotiff.py
    review/
      builder.py
      templates/
      static/
    resources/
  tests/
    fixtures/
  tools/
    package_qgis_plugin.py
    validate_release_archive.py
    verify_release_version.py
  docs/
  .github/workflows/
  CHANGELOG.md
  CONTRIBUTING.md
  LICENSE
  README.md
  FAKE_FARM_DATA_GENERATOR_SPECIFICATION.md
```

Generation modules must be reusable by both Processing algorithms and the complete-run orchestrator. Network, export, and review code must not be embedded in the numerical generation functions.

## 19. Compatibility and dependencies

- Minimum QGIS version: 3.28.
- Maximum metadata target: 4.99 until a breaking incompatibility is known.
- Use QGIS and GDAL APIs bundled with supported QGIS distributions.
- Avoid mandatory pip-installed packages.
- Isolate version-sensitive Processing parameters behind compatibility helpers.
- Avoid Windows-only paths and shell commands.
- Use `pathlib` and UTF-8 text files.
- Validate on Windows, macOS, and Linux where practical.

Automated QGIS smoke testing should cover QGIS 3.34, 3.40, 3.44, and 4.2 container images. QGIS 3.28 remains a manual compatibility target if a maintained container is unavailable.

## 20. Error handling

Errors must be actionable and name the field, year, data type, operation, or file involved.

Required handling includes:

- Invalid or empty input geometry.
- Unsupported or missing CRS.
- More than 20 fields, 5,000 acres, or 10 years.
- Invalid planter geometry.
- Minimum values greater than maximum values.
- Missing crop assignments.
- CDL service timeout, invalid response, or missing year.
- Unwritable output folder.
- Output-format driver unavailable.
- Insufficient disk space when it can be estimated.
- Canceled runs.
- HTML preview limits.

Remote crop lookup uses bounded timeouts and retry limits. When an API year is unavailable, the complete workflow may infer it only from usable nearby API observations; otherwise it identifies the unresolved field-year and blocks generation.

## 21. Testing requirements

### 21.1 Unit tests

- Seed derivation is stable by field, year, data type, and operation.
- Unit conversion preserves equivalent settings.
- Date variation stays within its configured window.
- Selected-feature behavior is correct.
- Field IDs are deterministic.
- API crop histograms exclude nonagricultural pixels and preserve dominance provenance.
- Nonagricultural CDL classes are not chosen as crops.
- Rotation inference is deterministic and distinct from observed API provenance.
- Soil intervals produce the correct years.
- Soil Regular Grid and Random placement are deterministic and stay within each field.
- Soil variability uses the current 0.5, 1.5, and 3.0 multipliers.
- Soil phosphorus and potassium support ppm and lb/acre profiles with explicit units.
- Unattributed soil mode omits nutrient columns.
- Unattributed soil mode disables the interpolated surface.
- Soil IDW and ordinary-kriging cells use only points from the matching field.
- Ordinary-kriging weights sum to one, exact sample locations preserve their sample values, and constant sample fields remain constant.
- Spherical, exponential, and Gaussian variograms produce bounded normalized semivariances.
- Kriging range, nugget, variance, and any IDW fallback are recorded correctly.
- Row-unit offsets match row count and spacing.
- Planting passes honor automatic or manual bearings and remain clipped to their matching field.
- Planting center and row-unit records retain stable links, timestamps, units, headland state, and selected variability.
- Planting surface cells use point means when logged points occur in the cell and the deterministic `generated_centroid` method otherwise.
- Flat application rates still have bounded logging variation.
- Point estimates are within documented tolerance of actual counts.
- Shapefile aliases are stable and reversible.
- Fake-data metadata is always present.

### 21.2 QGIS integration tests

- Plugin/provider registration.
- All five algorithms are discoverable.
- Single-field and multi-field runs.
- Multi-year complete run.
- All supported vector formats.
- Polygon-grid surface creation.
- Valid output geometry and expected fields.
- Cancellation and incomplete manifest behavior.
- Multi-layer USDA CDL crop lookup with one combined request per year and field-sized fallback.
- Mocked CroplandCROS success, timeout, invalid data, missing-year rotation inference, and unresolved-year failure.
- Review HTML and companion assets.

### 21.3 Viewer tests

- Left/right selectors are independent.
- Compare divider moves and resets.
- Disabling comparison leaves the left layer visible and hides the right controls.
- Field selection shows exactly one field and zooms to it.
- Filters work across year, data type, and operation.
- Attribute/ramp changes update the legend.
- Soil points are complete.
- High-volume point layers show deterministic samples and accurate totals.
- Fake-data warning is visible.
- Local layers load through `file://`.
- Missing internet affects basemaps but not local data.

### 21.4 Release tests

- Plugin ZIP has one correct top-level plugin folder.
- Metadata version matches the Git tag.
- Archive contains no absolute local paths, credentials, caches, or generated private data.
- Source compiles under the supported Python/QGIS matrix.
- Package checksum is generated.
- Demo outputs contain fake-data labeling.

## 22. Release workflow

The repository will use GitHub Actions for:

- Python compilation and unit tests.
- QGIS compatibility smoke tests.
- Plugin ZIP packaging and validation.
- Tag/version consistency.
- SHA-256 checksum creation.
- GitHub Release publication.
- GitHub Pages deployment.

The plugin will initially be distributed through GitHub Releases. Submission to the official QGIS Plugin Repository may be evaluated after v1.0.0 is validated.

## 23. V1 acceptance criteria

V1 is complete when all of the following are true:

1. A user can install one ZIP and see the Fake Farm Data Generator provider.
2. All five tools register and run.
3. The complete tool can generate any selected subset of soil, planting, application, and yield data in one run.
4. A run supports one to 20 fields, up to 5,000 acres, and up to 10 years.
5. The complete dialog pulls crops on demand from USDA CroplandCROS and labels missing-year rotation estimates with explicit provenance.
6. Every field-year used for planting or yield has an explicit API-observed or rotation-inferred crop assignment.
7. Soil tests follow first year, interval, and optional final year; support grid or random points, current-tool variability settings, ppm or lb/acre P and K, and IDW or ordinary-kriging polygon-grid surfaces.
8. Planting can create planter-center points by default, row-unit points, both, crop-specific defaults, advanced planter/furrow metrics, and selected polygon-grid surfaces.
9. As-applied data supports all six v1 operation categories, multiple operations, and flat or variable rates.
10. Yield creates monitor-style points and a polygon-grid surface.
11. Imperial and metric configurations generate correctly labeled values.
12. One master seed reproduces the same output.
13. Point counts are estimated before execution and actual counts are reported afterward.
14. The user can export the agreed v1 formats.
15. Every output is permanently and visibly labeled as fake data.
16. Every successful run creates a portable HTML review with layer filters and split comparison.
17. Soil points are complete in the viewer, while high-volume logs may be sampled only for display.
18. The plugin passes unit, QGIS integration, viewer, packaging, and compatibility checks.
19. The repository contains installation, usage, schema, contributing, license, and release documentation.
20. GitHub Pages hosts the documentation and demo site.

## 24. Implementation sequence

1. Scaffold the standalone GPL-3.0-or-later QGIS plugin and test packaging.
2. Implement shared configuration, field identity, CRS, units, seeds, dates, pass geometry, manifests, and point estimation.
3. Refactor and import the existing soil and yield logic without changing the original ASM repository.
4. Implement crop profiles, on-demand CroplandCROS access, temporary downloads, field-year classification, and rotation inference for unavailable years.
5. Implement planting center/row-unit points and polygon-grid surfaces.
6. Implement editable application operations, point logs, and polygon-grid surfaces.
7. Implement the complete-run tabbed dialog and JSON recipes.
8. Implement multi-format exporters and yearly run folders.
9. Implement the portable HTML review and split comparison.
10. Add automated tests, QGIS compatibility validation, packaging, GitHub workflows, documentation, and demo artifacts.

## 25. Implementation references

The initial implementation reuses behavior and lessons from the maintainer's
earlier fake soil-test script, fake yield script, and Field Boundary Tools
portable comparison review while remaining a new standalone repository. Those
private local source paths are intentionally not part of the public project.

External technical references:

- USDA NASS developer resources: <https://www.nass.usda.gov/developer/>
- USDA CroplandCROS CDL image service: <https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer>
- USDA Cropland Data Layer information: <https://www.nass.usda.gov/Research_and_Science/Cropland/>
- QGIS plugin metadata: <https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/plugins/plugins.html>
- QGIS Processing provider development: <https://docs.qgis.org/latest/en/docs/pyqgis_developer_cookbook/processing.html>

## 26. Decisions intentionally deferred beyond this specification

These items are not blockers for the initial implementation:

- Final icon and visual branding.
- Official QGIS Plugin Repository submission timing.
- Additional crop profiles after the v1 list.
- Additional machine exchange formats.
- Optional Google Earth Engine or Esri Living Atlas crop-source adapters.
- Advanced relationships between generated data types, which would be a separate future mode and must not replace the clearly fake v1 behavior.
