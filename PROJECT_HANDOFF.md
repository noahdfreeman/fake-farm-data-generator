# Fake Farm Data Generator — V1 project handoff

Updated: 2026-08-05  
Project status: Paused pending OSGeo account approval and official QGIS Plugin Repository submission  
Current plugin version: `1.0.0`  
Current branch: `main`

## Public project

- Repository: <https://github.com/noahdfreeman/fake-farm-data-generator>
- Documentation: <https://noahdfreeman.github.io/fake-farm-data-generator/>
- V1 release: <https://github.com/noahdfreeman/fake-farm-data-generator/releases/tag/v1.0.0>
- Issue tracker: <https://github.com/noahdfreeman/fake-farm-data-generator/issues>

The public release is stable, not marked experimental, and licensed under
GPL-3.0-or-later. The `v1.0.0` tag points to commit
`1ed9ab14fd915f88ac6e061a623f61341ae6ba9c`. Documentation and CI-only
follow-up work is on `main`; the plugin source remains the released V1 source.

## Release assets

| Asset | Purpose | Size | SHA-256 |
| --- | --- | ---: | --- |
| `fake_farm_data_generator-1.0.0.zip` | QGIS **Install from ZIP** package | 429,212 bytes | `c87f5a08aef91707aefc74d83dab226d11c2624d5bd548f669eb679a522311e4` |
| `fake-farm-data-demo.zip` | Small two-field generated-data demo | 1,879,206 bytes | `f5acadfc41f1c9e1e6ce956d71325405d2d0039451703a3d043240078cd92fed` |
| `Fake_Farm_Data_Example.zip` | Full four-field, four-year generated example | 368,243,765 bytes | `bf8537471c54f7e07f3909d26b19769e3f6234636aee5f5eb334b8a6f58febeb` |
| `Field_Examples.zip` | Three GeoPackage boundary inputs | 18,547 bytes | `fb0568ac48a15a6ff6fd6d81823b38f17409fc5c3b80d1e8f25a48602cf13c0f` |

Checksum sidecars for the plugin, full example, and field examples are attached
to the release.

## Completed V1 behavior

- One QGIS plugin with a toolbar icon, Plugins-menu entry, Processing provider,
  complete-run dialog, and four individual Processing algorithms.
- Soil-test, planting, as-applied, and yield generation for multiple polygon
  layers, fields, and crop years.
- Up to 20 fields, 5,000 acres, and 10 years per complete run.
- Imperial/Metric selection, US Central default timezone, deterministic seeds,
  saved recipes, preflight record/runtime estimates, incremental progress,
  cancellation, and detailed completion summaries.
- USDA CroplandCROS/CDL crop lookup with crop dropdown overrides and rotation
  inference for missing years.
- Soil regular-grid or random sampling, boundary setback, variability controls,
  nutrient units, IDW, and Ordinary Kriging polygon-grid surfaces.
- Planting center or row-unit points, crop-specific defaults, advanced planter
  metrics, perimeter headlands, and polygon-grid surfaces.
- Multiple flat- or variable-rate application operations with realistic bounded
  logging variation, perimeter headlands, and surfaces.
- Natural-looking yield variation, crop profiles, end rows/headlands, and
  polygon-grid surfaces.
- GeoPackage, Shapefile, GeoJSON, CSV-point, and optional GeoTIFF outputs.
- Portable branded Leaflet review with permanent field boundaries, field/year/
  data-type/operation filtering, preferred default attributes, opacity control,
  compare-off startup, and split-screen comparison.
- Permanent fake-data warnings in layers, manifests, exported files, review
  pages, documentation, and examples.

## Important decisions and fixes from development

- The term **fake data** is intentional. V1 does not correlate data types or use
  real soil, terrain, weather, or management layers to model agronomic truth.
- Crop identity may come from USDA CDL, but generated values remain independent
  fake data.
- Field boundaries are always visible in the HTML review and are not selectable
  as a data layer.
- Clicking anywhere inside another boundary, clicking its outline, or changing
  the Field dropdown selects, filters, and zooms to that field.
- HTML reviews generated before the boundary-selection fix are static and are
  not retroactively changed. New runs use the corrected viewer.
- GeoPackage consolidation and streamed worker progress materially improved
  complete-run performance and responsiveness.
- QGIS 3.x Docker images may raise a native Qt/PyQt shutdown fault only after
  all smoke assertions finish. The CI runner accepts this condition only when
  the final `QGIS_SMOKE_OK` marker is present; genuine assertion failures still
  fail the job.

## Example-data notes

- The full example expands to approximately 8.6 GB. Its internal manifest says
  generator `0.30.0` because it was created immediately before the V1 version
  bump; it uses the V1 schema and is documented as a pre-release-generated V1
  example.
- The full example's embedded HTML was updated with the final boundary-click
  fix before publication. The maintainer's original archive was not changed.
- The supplied demo-field archive contained one exact duplicate geometry in
  `Field 2.gpkg`. The public copy removes that duplicate and contains exactly
  three unique fields: 72.95, 56.87, and 99.16 acres. The maintainer's original
  archive was not changed.

## Validation state

- Dependency-free unit suite: 82 tests passing.
- Packaging, version verification, archive validation, and private-path checks
  pass.
- Complete QGIS smoke tests pass on official QGIS 3.34, 3.40, 3.44, and 4.2
  Linux images and the current macOS QGIS 4.0.3 application bundle.
- Windows QGIS 3.44.6 full smoke assertions pass locally.
- GitHub `main` CI, QGIS compatibility, release publication, and Pages
  deployment are green.
- Installed local QGIS profile contains plugin version `1.0.0` and the same
  review builder as the repository. QGIS was running when this handoff was
  written, so restart QGIS before relying on newly synced Python modules.

## Remaining external step: official QGIS publication

Do not create another GitHub release merely to submit the plugin. After the
maintainer's OSGeo ID is approved:

1. Sign in at <https://plugins.qgis.org/> with the OSGeo account.
2. Choose **Share a plugin**.
3. Upload `fake_farm_data_generator-1.0.0.zip` from the existing V1 GitHub
   release. Do not upload either generated-data example or `Field_Examples.zip`
   as the plugin package.
4. Confirm the imported metadata shows version `1.0.0`, minimum QGIS `3.28`,
   maximum QGIS `4.99`, GPL licensing, public repository, issue tracker,
   homepage, icon, and `experimental=False`.
5. Submit for staff review and wait for approval. Do not retag or overwrite V1
   unless QGIS validation identifies a real plugin-package defect.
6. After approval, install the repository version in a clean QGIS profile and
   run a small soil/yield generation test plus the portable HTML review.
7. Add the official QGIS plugin-page link to the root README, documentation
   site, and this handoff.

If a correction is required after V1 publication, bump to `1.0.1`; update
`metadata.txt`, generator version strings, changelog, release notes, and tests;
run all validation; then create a new `v1.0.1` tag and upload the new ZIP.

## Resume commands

```powershell
git switch main
git pull --ff-only
git status --short --branch
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q fake_farm_data_generator tests tools
python tools/verify_release_version.py
python tools/package_qgis_plugin.py
python tools/validate_release_archive.py dist/fake_farm_data_generator-1.0.0.zip
gh run list --branch main --limit 10
gh release view v1.0.0
```

## Key files

- `README.md` — public overview, screenshots, installation, and examples.
- `FAKE_FARM_DATA_GENERATOR_SPECIFICATION.md` — product and technical scope.
- `V1_IMPLEMENTATION_STATUS.md` — acceptance-criteria evidence.
- `RELEASE_NOTES.md` and `CHANGELOG.md` — release summary and history.
- `docs/development-and-release.md` — validation and release workflow.
- `fake_farm_data_generator/metadata.txt` — official QGIS metadata.
- `fake_farm_data_generator/complete_dialog.py` — primary user interface.
- `fake_farm_data_generator/review/builder.py` — portable HTML review.
- `.github/workflows/` — CI, compatibility, release, and Pages workflows.

## Clean stopping point

There are no known V1 implementation blockers. Resume this project when the
OSGeo account is approved or when a confirmed V1 bug/feature request is ready
for a patch release.
