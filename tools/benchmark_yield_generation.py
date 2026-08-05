"""Run a repeatable high-volume yield benchmark inside QGIS Python."""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import shutil
import sys
import time
from pathlib import Path

from qgis.core import QgsApplication


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--review", action="store_true")
    args = parser.parse_args()

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)

    prefix = os.environ.get("QGIS_PREFIX_PATH")
    if prefix:
        QgsApplication.setPrefixPath(prefix, True)
        plugins_path = Path(prefix) / "python" / "plugins"
        if plugins_path.is_dir():
            sys.path.insert(0, str(plugins_path))
    app = QgsApplication([], False)
    app.initQgis()
    provider = None
    try:
        from processing.core.Processing import Processing
        import processing

        from fake_farm_data_generator.provider import FakeFarmDataGeneratorProvider

        Processing.initialize()
        provider = FakeFarmDataGeneratorProvider()
        QgsApplication.processingRegistry().addProvider(provider)
        parameters = {
            "INPUT": str(ROOT / "tests" / "fixtures" / "two_fields.geojson"),
            "CROP_YEAR": 2025,
            "CROP_NAME": "Corn",
            "MIN_DRY_YIELD": 120.0,
            "MAX_DRY_YIELD": 240.0,
            "MIN_MOISTURE": 12.0,
            "MAX_MOISTURE": 25.0,
            "STANDARD_MOISTURE": 15.5,
            "SWATH_WIDTH": 30.0,
            "NOMINAL_SPEED": 4.0,
            "LOGGING_INTERVAL": 1.0,
            "HEADLAND_PASSES": 2,
            "HEADLAND_PENALTY": 10.0,
            "DIRECTION_MODE": 0,
            "VARIABILITY_LEVEL": 1,
            "CREATE_SURFACE": True,
            "SURFACE_GRID_SIZE": 30.0,
            "CREATE_REVIEW": args.review,
            "RANDOM_SEED": 303030,
            "OUTPUT_DIR": str(args.output),
        }
        profiler = cProfile.Profile()
        started = time.perf_counter()
        profiler.enable()
        result = processing.run(
            "fake_farm_data_generator:create_fake_yield_data", parameters
        )
        profiler.disable()
        elapsed = time.perf_counter() - started
        if args.profile:
            profiler.dump_stats(str(args.profile))
        manifest = json.loads(Path(result["MANIFEST"]).read_text(encoding="utf-8"))
        print(
            json.dumps(
                {
                    "elapsed_seconds": round(elapsed, 3),
                    "yield_points": manifest["counts"]["yield_points"],
                    "surface_cells": manifest["counts"]["surface_cells"],
                    "output_folder": result["OUTPUT_FOLDER"],
                }
            )
        )
    finally:
        if provider is not None:
            QgsApplication.processingRegistry().removeProvider(provider)
        app.exitQgis()


if __name__ == "__main__":
    main()
