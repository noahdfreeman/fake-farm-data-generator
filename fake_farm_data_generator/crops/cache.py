# SPDX-License-Identifier: GPL-3.0-or-later
"""Persistent cache paths for bounded CDL raster subsets."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def cached_files(root):
    """List only cache artifacts owned by this plugin."""

    directory = Path(root)
    if not directory.is_dir():
        return []
    return sorted({*directory.glob("cdl_*.tif"), *directory.glob("cdl_*.json")})


def clear_cached_files(root):
    """Delete plugin-owned cache artifacts and return the deleted paths."""

    deleted = cached_files(root)
    for path in deleted:
        path.unlink()
    return deleted


def cache_key(endpoint: str, year: int, extent, pixel_size: float, service_version: str = ""):
    normalized_extent = [round(float(value), 3) for value in extent]
    payload = {
        "endpoint": str(endpoint).rstrip("/"),
        "year": int(year),
        "extent": normalized_extent,
        "pixel_size": round(float(pixel_size), 6),
        "service_version": str(service_version),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return f"cdl_{int(year)}_{digest}", payload


class CdlCache:
    def __init__(self, root):
        self.root = Path(root)

    def paths(self, endpoint, year, extent, pixel_size, service_version=""):
        stem, metadata = cache_key(
            endpoint, year, extent, pixel_size, service_version
        )
        return self.root / f"{stem}.tif", self.root / f"{stem}.json", metadata

    def get(self, endpoint, year, extent, pixel_size, service_version=""):
        raster_path, metadata_path, expected = self.paths(
            endpoint, year, extent, pixel_size, service_version
        )
        if not raster_path.is_file() or not metadata_path.is_file():
            return None
        try:
            actual = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if actual.get("request") != expected or actual.get("status") != "complete":
            return None
        return raster_path

    def find_any(self, endpoint, year, extent, pixel_size):
        """Find a matching complete entry without requiring a live service version."""

        if not self.root.is_dir():
            return None, None
        expected_extent = [round(float(value), 3) for value in extent]
        expected_endpoint = str(endpoint).rstrip("/")
        for metadata_path in sorted(self.root.glob(f"cdl_{int(year)}_*.json")):
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            request = metadata.get("request", {})
            if (
                metadata.get("status") != "complete"
                or request.get("endpoint") != expected_endpoint
                or int(request.get("year", -1)) != int(year)
                or list(request.get("extent", [])) != expected_extent
                or abs(float(request.get("pixel_size", -1)) - float(pixel_size)) > 1e-6
            ):
                continue
            raster_path = metadata_path.with_suffix(".tif")
            if raster_path.is_file():
                return raster_path, metadata
        return None, None

    def store_metadata(self, metadata_path, request, **extra):
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"status": "complete", "request": request}
        payload.update(extra)
        Path(metadata_path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
