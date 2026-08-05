# V1 implementation status

Updated: 2026-08-05
Current validated build: 1.0.0

This status is evidence-based. A requirement is marked complete only when the
current source, tests, or packaged plugin demonstrates it.

## Acceptance criteria

| # | Requirement | Status | Current evidence |
| --- | --- | --- | --- |
| 1 | Install one ZIP and see the provider | Complete | Release archive validator and installed-profile QGIS smoke test |
| 2 | All five tools register and run | Complete | `tests/qgis_smoke_test.py` reports `algorithms=5` and executes every generator |
| 3 | Complete tool creates any selected subset | Complete | Orchestrator task construction plus soil/application and automatic-crop live runs |
| 4 | 20 fields, 5,000 acres, 10 years | Complete | Complete-run validation and dependency-free settings tests |
| 5 | USDA CDL API crops with rotation inference | Complete | API adapter tests, explicit pull workflow, per-year combined requests, and live API/inference payload validation |
| 6 | Explicit field-year crop assignment | Complete | Crop manager refuses unresolved assignments and the dialog serializes complete API/inference provenance |
| 7 | Soil schedules, placements, variability, units, IDW, kriging | Complete | Unit tests plus live grid, random, 150-foot boundary setback, IDW fallback, and ordinary-kriging outputs |
| 8 | Planting center, row-unit, both, crop defaults, advanced metrics, and surfaces | Complete | Live QGIS output/schema/count verification for all point types and 13 selectable surface metrics |
| 9 | Six application categories, multiple operations, flat/variable | Complete | Operation normalization tests and complete-run merged-operation live test |
| 10 | Yield points and polygon grid | Complete | Live QGIS output/schema/count verification including smooth spatial patterns and perpendicular end-row headings |
| 11 | Imperial and Metric output | Complete | Live-QGIS metric checks for all four generators |
| 12 | Reproducible master seed | Complete | Stable-seed tests and deterministic generator checks |
| 13 | Preflight estimates and final counts | Complete | Record and runtime preflight estimates, weighted overall progress, completion summary, recipes, manifests, and live count comparisons |
| 14 | GeoPackage, Shapefile, GeoJSON, CSV, GeoTIFF | Complete | Multi-format live-QGIS export validation |
| 15 | Permanent fake-data labeling | Complete | Schemas, manifests, README warning, review banner, and package tests |
| 16 | Portable filtered split-comparison review | Complete | Bundled branded Leaflet review, compare-off startup, permanent clickable background boundaries, county-tool-style center handle, left-layer-only mode, single-field filtering/zoom, tenths-rounded area, and generated HTML/data assertions |
| 17 | All soil points; sampled high-volume display only | Complete | Configurable review-limit tests and live displayed/total assertions |
| 18 | Unit, integration, viewer, packaging, compatibility checks | Partial | 81 unit tests, the Windows QGIS 3.44.6 full smoke assertions, and a direct isolated-worker review run pass for v1.0.0. The official Linux QGIS 3.34/3.40/3.44/4.2 matrix remains the earlier baseline until v1.0.0 is rerun through every target. A current-QGIS macOS workflow is prepared but has not yet run in GitHub Actions |
| 19 | Installation, usage, schema, contribution, license, release docs | Complete | Dedicated Pages-ready documentation plus README, specification, changelog, contribution guide, license, templates, and release workflows |
| 20 | GitHub Pages documentation and demo | Complete | Public repository, Pages workflow, screenshot documentation, downloadable example ZIP, and interactive all-generator demo are included in the V1 publication |

## Current validation commands

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q fake_farm_data_generator tests tools
python tools/package_qgis_plugin.py
python tools/validate_release_archive.py dist/fake_farm_data_generator-1.0.0.zip
```

Live validation currently uses:

- Windows QGIS 3.40.14 LTR through `python-qgis-ltr.bat`
- Windows QGIS 3.44.6 through `python-qgis.bat`
- Official Linux `qgis/qgis` images for 3.34, 3.40, 3.44, and 4.2
- Current QGIS application bundle on GitHub-hosted macOS through the prepared
  Homebrew-backed job (pending its first remote run)

The v1.0.0 Windows validation reports weighted overall progress, natural yield
patterns, pass-count headlands with planting/yield width matching, a live-checked
150-foot soil-point setback, permanent clickable background boundaries, tenths-rounded area, compare-off startup,
the branded plugin/review logo, county-tool-style center comparison handle, left-layer-only non-compare mode,
one-field-at-a-time filtering with automatic zoom, multi-layer boundary
normalization, data-type controls, ordinary kriging, all five algorithms,
complete-run consolidation, portable-review generation, streamed progress,
cancellation, and `canceled_status=incomplete`.

The Windows QGIS 3.44.6 headless suite reaches `QGIS_SMOKE_OK` after every
assertion, then the QGIS test host raises a native access violation during
`exitQgis()` teardown. A separate direct `qgis_process` complete run exits 0;
the teardown fault occurs after validation and outside the isolated generator.

## Remaining release gates

1. Confirm the first remote CI run, including the current-QGIS macOS job; do not
   mark macOS compatibility complete until that runtime test passes.
2. Submit version 1.0.0 to the official QGIS Plugin Repository after the
   maintainer's OSGeo account is approved.
