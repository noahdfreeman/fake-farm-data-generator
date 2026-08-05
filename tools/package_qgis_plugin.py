#!/usr/bin/env python3
"""Validate and package the QGIS plugin as an installable ZIP."""

from __future__ import annotations

import configparser
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "fake_farm_data_generator"
DIST = ROOT / "dist"
REQUIRED_FILES = {
    "__init__.py",
    "metadata.txt",
    "plugin.py",
    "provider.py",
    "README.md",
    "LICENSE",
}


def main() -> None:
    missing = sorted(name for name in REQUIRED_FILES if not (PLUGIN / name).is_file())
    if missing:
        raise SystemExit(f"Plugin is missing required files: {', '.join(missing)}")

    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PLUGIN / "metadata.txt", encoding="utf-8")
    metadata = parser["general"]
    required_metadata = (
        "name",
        "version",
        "qgisMinimumVersion",
        "qgisMaximumVersion",
        "description",
        "author",
        "repository",
        "tracker",
    )
    blank = [key for key in required_metadata if not metadata.get(key, "").strip()]
    if blank:
        raise SystemExit(f"Plugin metadata is blank: {', '.join(blank)}")

    DIST.mkdir(exist_ok=True)
    output = DIST / f"fake_farm_data_generator-{metadata['version']}.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PLUGIN.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            archive.write(path, path.relative_to(ROOT).as_posix())
    print(output)


if __name__ == "__main__":
    main()
