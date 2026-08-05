---
layout: default
title: Parameter reference
---

# Parameter reference

## Shared parameters

| Setting | Behavior |
| --- | --- |
| Input polygons | One or more checked polygon/multipolygon layers; selections within each layer take precedence |
| Unit system | Imperial by default; values are converted when changed in the dialog |
| Random seed | `0` creates a new seed; a positive integer reproduces the run |
| Crop years | Ten checkable buttons for the current year and previous nine years |
| Data types | Soil Tests, Planting, As-Applied, and Yield checkboxes; none selected by default |
| Timezone | IANA timezone dropdown; US Central Time (`America/Chicago`) by default |
| Crops | USDA/rotation result per field-year with a user-editable crop dropdown |
| Output formats | GeoPackage default; optional Shapefile, GeoJSON, point CSV, surface GeoTIFF |
| HTML review limit | 100–200,000 high-volume features per layer; default 20,000 |
| Output directory | Required first setting on General; parent directory for a new timestamped run folder |

## Soil-test parameters

| Setting | Default or range |
| --- | --- |
| Schedule | First year, 3-year interval, optional final year |
| Placement | Regular Grid or Random |
| Density | 2.5 acres/point by default; metric equivalent in Metric mode |
| Boundary setback | 150 feet by default; 45.72 meters in Metric mode |
| Fertility/variability | Low, Medium, or High |
| P and K units | ppm or lb/acre; Metric mode exports kg/ha equivalents |
| Surface | Enabled for attributed samples |
| Interpolation | Ordinary Kriging default; IDW alternative/fallback |
| Variogram | Spherical, Exponential, or Gaussian |
| Kriging range | `0` for automatic or a positive user-entered distance |
| Nugget ratio | 0–1 |

## Planting parameters

| Setting | Default |
| --- | --- |
| Point output | Planter-center by default; row-unit or both remain available |
| Planter | 16 rows, 30-inch spacing, 40-foot width |
| Population | 32,000 seeds/acre target within configurable bounds |
| Logging | 5 mph, 1-second interval |
| Direction | Automatic; manual bearing available |
| Headland | Two planter passes by default; physical width is pass count times planter width |
| Surface attributes | Population, speed, seed spacing, seed depth |

Crop tabs provide separate population bounds, seed depth, and planting date for
each supported crop. Point output additionally contains singulation, spacing
quality, skips, ride quality, ground contact, furrow moisture, furrow
temperature, uniform furrow, and clean furrow. These metrics can also be chosen
as polygon-grid attributes.

## Application parameters

Each operation specifies year, ID, category, product, flat/variable rate,
target/minimum/maximum and unit, equipment width, speed, logging interval,
headland pass count, direction, date/window, variability, and surface grid size.

## Yield parameters

Choose a crop profile, dry-yield range, moisture range and standard moisture,
swath width, speed, logging interval, headland pass count/penalty, direction,
harvest date/window, variability, and surface grid size.

The complete-run dialog calculates the default yield pass count from the physical
width of the planting headland so the yield and planting headland zones match.

The complete-run Yield tab provides an editable row for every supported crop.
Enable per-crop customization to set its minimum and maximum dry yield plus
minimum, maximum, and standard moisture. Values convert when the top-level unit
system changes.

The QGIS Processing dialog remains authoritative for numeric minimums and
maximums. Invalid relationships—such as minimum above maximum or inconsistent
planter geometry—stop before output generation.
