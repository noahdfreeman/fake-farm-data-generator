---
layout: default
title: Development and releases
---

# Development and releases

## Local checks

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall -q fake_farm_data_generator tests tools
python tools/verify_release_version.py
python tools/package_qgis_plugin.py
python tools/validate_release_archive.py dist/fake_farm_data_generator-<version>.zip
```

QGIS-dependent behavior must also pass `tests/qgis_smoke_test.py`; compilation
alone does not validate PyQGIS/GDAL execution.

## Automated workflows

- `ci.yml`: dependency-free test matrix, compilation, packaging, validation,
  checksum, and downloadable artifact.
- `qgis-smoke.yml`: official QGIS Docker images for 3.34, 3.40, 3.44, and 4.2,
  plus the current QGIS application bundle on a GitHub-hosted macOS runner.
- `release.yml`: verifies a `vX.Y.Z` tag, rebuilds the ZIP/checksum, and creates
  the GitHub release with those exact assets plus the public example-data ZIP.
- `pages.yml`: builds this documentation with GitHub Pages and deploys it from
  the `github-pages` environment.

Before enabling Pages, set repository **Settings → Pages → Build and deployment
→ Source** to **GitHub Actions**. Before tagging, update `metadata.txt`, source
generator versions, the root README, and the changelog together; the version
verifier rejects mismatches.

## Release checklist

1. Run unit, compilation, archive, supported-QGIS Docker, and macOS QGIS checks.
2. Inspect the ZIP for one plugin root and no caches, credentials, local paths,
   or generated private data.
3. Confirm every demo artifact is visibly labeled as fake.
4. Tag the validated commit as `vX.Y.Z`.
5. Verify the release ZIP checksum and install the released asset in QGIS.
6. Confirm Pages documentation and the demo comparison viewer are reachable.

See `CONTRIBUTING.md`, `CHANGELOG.md`, `LICENSE`, and
`V1_IMPLEMENTATION_STATUS.md` in the repository root.
