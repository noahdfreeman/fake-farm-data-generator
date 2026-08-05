# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded, cached access to the public USDA CroplandCROS ImageServer."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..cache import CdlCache


DEFAULT_ENDPOINT = "https://pdi.scinet.usda.gov/image/rest/services/CDL_WM/ImageServer"


class CroplandCrosSource:
    def __init__(
        self,
        cache_root,
        endpoint=DEFAULT_ENDPOINT,
        timeout_seconds=30,
        retries=1,
        user_agent="FakeFarmDataGenerator/0.17",
    ):
        self.endpoint = str(endpoint).rstrip("/")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.retries = max(0, int(retries))
        self.user_agent = user_agent
        self.cache = CdlCache(cache_root)
        self._service_info_cache = None
        self._available_years_cache = None

    def _json(self, url):
        last_error = None
        for _attempt in range(self.retries + 1):
            try:
                request = Request(url, headers={"User-Agent": self.user_agent})
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if "error" in payload:
                    raise RuntimeError(payload["error"].get("message", "ArcGIS service error"))
                return payload
            except Exception as error:  # network/JSON errors share bounded retry behavior
                last_error = error
        raise RuntimeError(f"CroplandCROS request failed: {last_error}") from last_error

    def service_info(self):
        if self._service_info_cache is None:
            self._service_info_cache = self._json(f"{self.endpoint}?f=json")
        return self._service_info_cache

    def available_years(self):
        if self._available_years_cache is not None:
            return list(self._available_years_cache)
        query = urlencode(
            {
                "where": "1=1",
                "outFields": "Year",
                "returnGeometry": "false",
                "returnDistinctValues": "true",
                "orderByFields": "Year",
                "f": "json",
            }
        )
        payload = self._json(f"{self.endpoint}/query?{query}")
        self._available_years_cache = sorted(
            int(feature["attributes"]["Year"])
            for feature in payload.get("features", [])
            if feature.get("attributes", {}).get("Year") is not None
        )
        return list(self._available_years_cache)

    def cached(self, year, extent_3857, pixel_size=30.0):
        """Return an offline cache hit without contacting the remote service."""

        path, metadata = self.cache.find_any(
            self.endpoint, year, extent_3857, float(pixel_size)
        )
        if path is None:
            return None
        request = metadata.get("request", {})
        return path, "cache", {
            "service_version": request.get("service_version", ""),
            "pixel_size": float(request.get("pixel_size", pixel_size)),
        }

    def fetch(self, year, extent_3857, pixel_size=30.0):
        """Return (path, source_name, metadata) for a requested Web Mercator bbox."""

        extent = tuple(float(value) for value in extent_3857)
        if len(extent) != 4 or extent[2] <= extent[0] or extent[3] <= extent[1]:
            raise ValueError("CroplandCROS extent must be xmin,ymin,xmax,ymax")
        offline_hit = self.cached(year, extent, pixel_size)
        if offline_hit is not None:
            return offline_hit
        info = self.service_info()
        service_version = str(info.get("currentVersion", ""))
        nominal_pixel = float(pixel_size or info.get("pixelSizeX") or 30.0)
        cached = self.cache.get(
            self.endpoint, year, extent, nominal_pixel, service_version
        )
        if cached is not None:
            return cached, "cache", {"service_version": service_version, "pixel_size": nominal_pixel}

        years = self.available_years()
        if int(year) not in years:
            raise ValueError(
                f"CDL year {year} is unavailable; service currently provides "
                f"{years[0]} through {years[-1]}"
            )
        width = max(1, int(math.ceil((extent[2] - extent[0]) / nominal_pixel)))
        height = max(1, int(math.ceil((extent[3] - extent[1]) / nominal_pixel)))
        maximum_width = int(info.get("maxImageWidth") or 4096)
        maximum_height = int(info.get("maxImageHeight") or 4096)
        if width > maximum_width or height > maximum_height:
            raise ValueError(
                f"CDL request would be {width} by {height} pixels, above the service "
                f"limit of {maximum_width} by {maximum_height}"
            )
        mosaic_rule = json.dumps(
            {
                "mosaicMethod": "esriMosaicAttribute",
                "where": f"Year = {int(year)}",
                "sortField": "Year",
                "sortValue": str(int(year)),
                "ascending": True,
                "mosaicOperation": "MT_FIRST",
            },
            separators=(",", ":"),
        )
        query = urlencode(
            {
                "bbox": ",".join(f"{value:.3f}" for value in extent),
                "bboxSR": "3857",
                "size": f"{width},{height}",
                "imageSR": "3857",
                "format": "tiff",
                "pixelType": "U8",
                "interpolation": "RSP_NearestNeighbor",
                "mosaicRule": mosaic_rule,
                "f": "json",
            }
        )
        response = self._json(f"{self.endpoint}/exportImage?{query}")
        href = response.get("href")
        if not href:
            raise RuntimeError("CroplandCROS export did not return a raster URL")

        raster_path, metadata_path, request_metadata = self.cache.paths(
            self.endpoint, year, extent, nominal_pixel, service_version
        )
        raster_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="ffdg_cdl_", suffix=".tif", delete=False, dir=raster_path.parent
            ) as temporary:
                temporary_path = Path(temporary.name)
                request = Request(href, headers={"User-Agent": self.user_agent})
                with urlopen(request, timeout=self.timeout_seconds) as response_stream:
                    shutil.copyfileobj(response_stream, temporary)
            if temporary_path.stat().st_size <= 0:
                raise RuntimeError("CroplandCROS returned an empty raster")
            os.replace(temporary_path, raster_path)
            temporary_path = None
            self.cache.store_metadata(
                metadata_path,
                request_metadata,
                href=href,
                width=int(response.get("width", width)),
                height=int(response.get("height", height)),
            )
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return raster_path, "croplandcros", {
            "service_version": service_version,
            "pixel_size": nominal_pixel,
        }
