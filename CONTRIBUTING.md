# Contributing

Contributions are welcome after the public repository is created. Keep generated records clearly labeled as fake and do not add real grower data, credentials, caches, or private field outputs to the repository.

## Development checks

From the repository root:

```powershell
python -m compileall -q fake_farm_data_generator tests
python -m unittest discover -s tests -p 'test_*.py' -v
python tools/verify_release_version.py
python tools/package_qgis_plugin.py
python tools/validate_release_archive.py dist/fake_farm_data_generator-<version>.zip
```

Live changes also require `tests/qgis_smoke_test.py` against supported QGIS runtimes. A release is not validated solely by normal Python compilation because generator execution depends on QGIS and GDAL APIs.

Linux QGIS compatibility runs use the official `qgis/qgis` images and
`tools/run_qgis_smoke_linux.sh`. The prepared GitHub Actions matrix covers QGIS
3.34, 3.40, 3.44, and 4.2. The macOS job installs the current QGIS application
bundle with the Homebrew `qgis` cask and runs the same full smoke test through
`tools/run_qgis_smoke_macos.sh`. A prepared workflow is not runtime evidence;
the macOS job must complete successfully before a release claims macOS
validation.

## Pull requests

- Describe the affected generator or workflow.
- Add or update dependency-free tests where possible.
- Add QGIS integration coverage for QGIS-dependent behavior.
- Preserve deterministic seed partitioning.
- Preserve the permanent fake-data warning in every artifact.
- Document schema, recipe, or user-visible changes in `CHANGELOG.md`.
