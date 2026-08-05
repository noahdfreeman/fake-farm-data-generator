#!/usr/bin/env python3
"""Check the basic structure and hygiene of a packaged plugin ZIP."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path, PurePosixPath


EXPECTED_ROOT = "fake_farm_data_generator"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_release_archive.py <plugin.zip>")
    archive_path = Path(sys.argv[1])
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if not names:
            raise SystemExit("Plugin archive is empty")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if roots != {EXPECTED_ROOT}:
            raise SystemExit(f"Unexpected archive roots: {sorted(roots)}")
        required = {
            f"{EXPECTED_ROOT}/__init__.py",
            f"{EXPECTED_ROOT}/metadata.txt",
            f"{EXPECTED_ROOT}/plugin.py",
            f"{EXPECTED_ROOT}/provider.py",
            f"{EXPECTED_ROOT}/complete_dialog.py",
            f"{EXPECTED_ROOT}/algorithms/soil_tests.py",
            f"{EXPECTED_ROOT}/algorithms/planting.py",
            f"{EXPECTED_ROOT}/algorithms/applications.py",
            f"{EXPECTED_ROOT}/algorithms/yield_data.py",
            f"{EXPECTED_ROOT}/algorithms/complete_dataset.py",
            f"{EXPECTED_ROOT}/core/application_operations.py",
            f"{EXPECTED_ROOT}/core/complete_settings.py",
            f"{EXPECTED_ROOT}/core/gpkg_metadata.py",
            f"{EXPECTED_ROOT}/core/gpkg_consolidation.py",
            f"{EXPECTED_ROOT}/core/point_estimator.py",
            f"{EXPECTED_ROOT}/core/preflight_review.py",
            f"{EXPECTED_ROOT}/core/progress.py",
            f"{EXPECTED_ROOT}/core/review_settings.py",
            f"{EXPECTED_ROOT}/crops/cdl_classes.py",
            f"{EXPECTED_ROOT}/crops/resolver.py",
            f"{EXPECTED_ROOT}/crops/cache.py",
            f"{EXPECTED_ROOT}/crops/manager.py",
            f"{EXPECTED_ROOT}/crops/sources/local_cdl.py",
            f"{EXPECTED_ROOT}/crops/sources/croplandcros.py",
            f"{EXPECTED_ROOT}/exporters/vector.py",
            f"{EXPECTED_ROOT}/review/builder.py",
            f"{EXPECTED_ROOT}/review/static/leaflet.js",
            f"{EXPECTED_ROOT}/review/static/leaflet.css",
            f"{EXPECTED_ROOT}/review/static/LEAFLET_LICENSE.txt",
            f"{EXPECTED_ROOT}/resources/fake_farm_data_generator.png",
        }
        missing = sorted(required - set(names))
        if missing:
            raise SystemExit(f"Archive is missing required files: {', '.join(missing)}")
        forbidden = [
            name
            for name in names
            if "__pycache__" in PurePosixPath(name).parts
            or name.endswith((".pyc", ".pyo"))
            or ":\\" in name
        ]
        if forbidden:
            raise SystemExit(f"Archive contains forbidden paths: {forbidden}")
    print(f"Validated {archive_path}")


if __name__ == "__main__":
    main()
