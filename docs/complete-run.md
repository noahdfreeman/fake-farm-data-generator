---
layout: default
title: Complete-run workflow
---

# Complete-run workflow

The complete tool is the recommended interactive workflow. Launching **Create
Complete Fake Farm Dataset** from the Processing Toolbox opens the same compact
seven-tab builder available from the plugin menu and its icon toolbar button. It calls the same
generation code as the four independent Processing algorithms; no JSON input is
required.

## 1. General

Check one or more polygon layers, optionally select field features within any
checked layer, map field identity columns, choose Imperial or Metric units,
select the data types to create, select up to 10 year buttons, choose a timezone,
set a master random seed, and select an output parent folder. The current year
and US Central Time are selected initially; no data type is selected automatically.

When features are selected, only the selection is processed. With no selection,
the dialog previews the count and acreage before using every feature.

## 2. Years and crops

Planting and yield require a crop for every field-year. Select **Pull Crops from
USDA CDL** to query the public CroplandCROS API. Unavailable selected years are
estimated from nearby API years and clearly labeled `rotation_inference`. Every
field-year crop is a dropdown, so the user may replace an API or rotation suggestion.

## 3. Choose generators

Enable any combination of soil tests, planting, applications, and yield. Each
tab exposes the settings used by the corresponding individual tool. The
Applications tab supports multiple ordered operations and an **All years** row.
The Soil Tests tab includes the first sampling year, final sampling year, and
interval. The Yield tab includes an optional per-crop table for overriding dry
yield and moisture ranges.

The Planting tab defaults to planter-center records. Nested crop tabs hold each
crop's population, seed depth, and typical planting date. Planting output also
includes fake planter-quality and furrow-condition metrics.

## 4. Outputs and review

Choose GeoPackage and any derivatives. The HTML-review feature limit applies to
large machine-log and polygon-surface layers; every soil-test point is always
included. The default is 20,000 displayed features per high-volume layer.

## 5. Preflight and run

Select **Review generation**. The final page reports field scope, acreage,
years, data types, crop-review status, estimated points and cells, formats,
network requirements, destination, and runtime warnings. Generation is enabled
only after validation succeeds.

During execution, a progress dialog reports the current field or component,
percent complete, records created, elapsed time, and estimated remaining time.
Generation runs in an isolated `qgis_process` worker, keeping desktop QGIS
responsive and preventing a worker fault from terminating the desktop process.
A canceled or failed run is marked `incomplete` and never claims a completed review.

## Recipes

Use **Save recipe** to store the dialog configuration before running. The loader
accepts both dialog recipes and the `run_recipe.json` written by a completed
run. Boundary layers are deliberately selected fresh; generation settings,
mapped columns, checked years, timezone, and output destination are restored.
