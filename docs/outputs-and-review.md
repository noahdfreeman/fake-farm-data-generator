---
layout: default
title: Outputs and portable review
---

# Outputs and portable review

## Run folder

```text
Fake_Farm_Data_<timestamp>/
  README_FAKE_DATA.txt
  run_manifest.json
  run_recipe.json
  field_name_map.json              # when Shapefile is selected
  fake_farm_data_review.html
  fake_farm_data_review_data/
  component_manifests/
  component_sources/
  <year>/
    fake_farm_data_<year>.gpkg
    shapefile/                     # optional
    geojson/                       # optional
    csv/                           # optional
    geotiff/                       # optional
```

The yearly GeoPackage is canonical and can contain boundaries, scheduled soil
points/surfaces, planting center/row/surface layers, merged applications,
yield points/surfaces, and registered run metadata. Component sources are kept
for provenance and are not the public canonical outputs.

## Portable review

Open `fake_farm_data_review.html` while keeping its companion data folder next
to it. Bundled Leaflet assets allow local layers to display through `file://`.
Online basemap tiles still require internet access.

The review provides:

- Hybrid, Satellite, and Streets basemaps.
- Independent left and right layer, attribute, and color-ramp selectors while comparison is enabled.
- A county-tool-style draggable vertical divider with a circular center handle.
- A left-layer-only view that hides the divider and right controls when comparison is disabled.
- A required single-field selector that filters all displayed layers and zooms to the chosen field.
- Year, data-type, and operation filters.
- The bundled product logo, legends, popups, formatted summary cards, and extent reset.
- Displayed-versus-total counts and sampling provenance.

All soil-test points are included. High-volume machine logs and polygon grids
are deterministically sampled only in the browser representation when they
exceed the configured limit. Raw exports are never sampled or simplified.

The fake-data warning is persistent and cannot be permanently dismissed.
