#!/usr/bin/env python3
"""Build the small public fake-data demo with an installed QGIS runtime."""

from __future__ import annotations

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path

from qgis.core import QgsApplication


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = ROOT / "docs" / "demo"
TARGET = DEMO_ROOT / "sample_run"
ARCHIVE = DEMO_ROOT / "fake-farm-data-demo.zip"


def _sanitize_recipe(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output_directory"] = "."
    payload["local_cdl_path"] = ""
    payload["cdl_cache_directory"] = ""
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _verify_public_text(root):
    forbidden = {str(ROOT), str(ROOT).replace("\\", "/")}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {
            ".txt",
            ".json",
            ".html",
            ".js",
            ".css",
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(value in text for value in forbidden):
            raise RuntimeError(f"Demo contains a local workspace path: {path}")
        if path.name not in {"leaflet.js", "leaflet.css"} and "FAKE DATA" not in text:
            if path.name in {"run_manifest.json", "run_recipe.json", "README_FAKE_DATA.txt"}:
                raise RuntimeError(f"Demo metadata is missing the fake-data warning: {path}")


def _zip_demo():
    if ARCHIVE.exists():
        raise RuntimeError(f"Demo archive already exists: {ARCHIVE}")
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(TARGET.rglob("*")):
            if path.is_file():
                archive.write(
                    path,
                    (Path("fake-farm-data-demo") / path.relative_to(TARGET)).as_posix(),
                )


def main():
    if TARGET.exists() or ARCHIVE.exists():
        raise SystemExit(
            "Demo output already exists. Review and remove docs/demo/sample_run and "
            "docs/demo/fake-farm-data-demo.zip before rebuilding."
        )
    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
        plugin_path = Path(prefix) / "python" / "plugins"
        if plugin_path.is_dir():
            sys.path.insert(0, str(plugin_path))
    sys.path.insert(0, str(ROOT))
    app = QgsApplication([], False)
    app.initQgis()
    provider = None
    generated = None
    try:
        from processing.core.Processing import Processing

        Processing.initialize()
        import processing

        from fake_farm_data_generator.provider import FakeFarmDataGeneratorProvider

        provider = FakeFarmDataGeneratorProvider()
        if not QgsApplication.processingRegistry().addProvider(provider):
            raise RuntimeError("Could not register Fake Farm Data Generator provider")
        result = processing.run(
            "fake_farm_data_generator:create_complete_fake_farm_dataset",
            {
                "INPUT": str(ROOT / "tests" / "fixtures" / "two_fields.geojson"),
                "FIELD_ID_FIELD": "field_name",
                "YEARS": "2025",
                "CREATE_SOIL": True,
                "SOIL_SETTINGS_JSON": json.dumps(
                    {
                        "placement": "Regular Grid",
                        "sample_density": 10,
                        "variability_level": "Medium",
                        "create_surface": True,
                        "surface_grid_size": 250,
                        "interpolation_method": "Ordinary Kriging",
                    }
                ),
                "CREATE_PLANTING": True,
                "PLANTING_SETTINGS_JSON": json.dumps(
                    {
                        "point_output": "Both",
                        "planter_width": 20,
                        "row_units": 2,
                        "row_spacing": 120,
                        "logging_interval": 20,
                        "surface_grid_size": 250,
                    }
                ),
                "CREATE_APPLICATIONS": True,
                "APPLICATION_OPERATIONS_JSON": json.dumps(
                    [
                        {
                            "year": 2025,
                            "operation_id": "DEMO_VRA_001",
                            "operation_type": "Dry Fertilizer",
                            "product_name": "Fake Demo Blend",
                            "rate_mode": "Variable Rate",
                            "target_rate": 150,
                            "min_rate": 100,
                            "max_rate": 200,
                            "rate_unit": "lb/acre",
                            "equipment_width": 120,
                            "logging_interval": 20,
                            "surface_grid_size": 250,
                        }
                    ]
                ),
                "CREATE_YIELD": True,
                "YIELD_SETTINGS_JSON": json.dumps(
                    {
                        "swath_width": 100,
                        "logging_interval": 30,
                        "surface_grid_size": 250,
                    }
                ),
                "CROP_LOOKUP_MODE": 0,
                "CROP_PROFILE": 0,
                "OUTPUT_FORMATS": [0],
                "REVIEW_MAX_FEATURES": 1000,
                "RANDOM_SEED": 20260804,
                "OUTPUT_DIR": str(DEMO_ROOT),
            },
        )
        generated = Path(result["OUTPUT_FOLDER"])
    finally:
        if provider is not None:
            QgsApplication.processingRegistry().removeProvider(provider)
        app.exitQgis()
    if generated is None or not generated.is_dir():
        raise RuntimeError("Demo generation did not return a run folder")
    shutil.move(str(generated), str(TARGET))
    _sanitize_recipe(TARGET / "run_recipe.json")
    _verify_public_text(TARGET)
    _zip_demo()
    print(f"DEMO_OK folder={TARGET} archive={ARCHIVE}")


if __name__ == "__main__":
    main()
