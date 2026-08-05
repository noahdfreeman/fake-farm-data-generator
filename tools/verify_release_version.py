#!/usr/bin/env python3
"""Verify that plugin, documentation, and optional Git tag versions agree."""

from __future__ import annotations

import configparser
import os
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
METADATA = ROOT / "fake_farm_data_generator" / "metadata.txt"
VERSION_FILES = (
    ROOT / "fake_farm_data_generator" / "complete_dialog.py",
    ROOT / "fake_farm_data_generator" / "algorithms" / "soil_tests.py",
    ROOT / "fake_farm_data_generator" / "algorithms" / "planting.py",
    ROOT / "fake_farm_data_generator" / "algorithms" / "applications.py",
    ROOT / "fake_farm_data_generator" / "algorithms" / "yield_data.py",
    ROOT / "fake_farm_data_generator" / "algorithms" / "complete_dataset.py",
)


def metadata_version():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(METADATA, encoding="utf-8")
    version = parser.get("general", "version", fallback="").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Invalid metadata version: {version!r}")
    return version


def normalize_tag(tag):
    text = str(tag or "").strip()
    return text[1:] if text.casefold().startswith("v") else text


def verify(expected_tag=""):
    version = metadata_version()
    problems = []
    expected = normalize_tag(expected_tag)
    if expected and expected != version:
        problems.append(f"tag version {expected} does not match metadata {version}")

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## {version} -" not in changelog:
        problems.append(f"CHANGELOG.md has no release heading for {version}")
    root_readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if version not in root_readme:
        problems.append(f"README.md does not mention {version}")

    for path in VERSION_FILES:
        text = path.read_text(encoding="utf-8")
        if version not in text:
            problems.append(f"{path.relative_to(ROOT)} does not contain {version}")
    if problems:
        raise ValueError("; ".join(problems))
    return version


def main():
    requested_tag = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.environ.get("GITHUB_REF_NAME", "")
    )
    try:
        version = verify(requested_tag)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"Release versions agree: {version}")


if __name__ == "__main__":
    main()
