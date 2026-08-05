---
layout: default
title: Output schemas
---

# Output schemas

Fields may be shortened in Shapefile output; `field_name_map.json` records the
mapping. GeoPackage is the reference schema.

## Common provenance

Every generated feature includes, where the format permits:

`fake_data`, `fake_warning`, `generator_name`, `generator_version`, `run_id`,
`created_at`, `master_seed`, `child_seed`, `unit_system`, `data_type`,
`field_id`, `field_name`, `farm_name`, `grower_name`, and `crop_year`.

Planting and yield also include `crop_name`, `crop_code`, `crop_pct`,
`crop_source`, `crop_source_year`, `crop_resolution`, `crop_lookup_at`, and
`crop_overridden`.

## Soil-test points

Identity/date fields include `sample_id`, `sample_date`, `sample_depth`,
`lab_name`, density and unit, placement, fertility/variability, latitude, and
longitude. Attributed mode adds `P`, `K`, `pH`, `bpH`, `OM`, `CEC`, `Ca`, `Mg`,
`B`, `Cu`, `Fe`, `Mn`, and `Zn`, with explicit P/K units.

Soil surface cells include interpolation method, source-point count, grid size,
variogram model/range/nugget, kriging variance, fallback state, and every
interpolated nutrient.

## Planting points and surfaces

Point fields include planting/center IDs, record type, pass, row unit, section
state, timestamp/timezone, heading, speed, population, seed spacing, seed depth,
row spacing, planter width, and headland state. Surface cells include the
selected agronomic attributes, source-point count, method, heading, and grid size.

## As-applied points and surfaces

Fields include application and operation IDs, category, product, rate mode,
target and actual rate with unit, pass, timestamp/timezone, heading, speed,
equipment width, section/headland state, and `fake_terrain_effect`. Surface cells
summarize actual rate, speed, and the fake terrain effect.

## Yield points and surfaces

Fields include yield/pass IDs, timestamp/timezone, heading, dry and wet yield
with unit, moisture and standard moisture, speed, swath width, logging interval,
and headland state. Surface cells add grid size, source-point count, and method.

Every GeoPackage also contains the registered nonspatial
`ffdg_run_metadata` table with run-level provenance and completion status.
