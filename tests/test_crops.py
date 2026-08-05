import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fake_farm_data_generator.crops.cache import (
    CdlCache,
    cache_key,
    cached_files,
    clear_cached_files,
)
from fake_farm_data_generator.crops.resolver import (
    apply_manual_override,
    classify_histogram,
)
from fake_farm_data_generator.crops.sources.croplandcros import CroplandCrosSource


class CropResolverTests(unittest.TestCase):
    def test_nonagricultural_pixels_are_excluded_from_dominance(self):
        assignment = classify_histogram(
            {1: 40, 5: 30, 121: 1000, 111: 250},
            "local_cdl",
            2024,
            30,
            lookup_at="2026-01-01T00:00:00-05:00",
        )
        self.assertEqual(assignment.crop_name, "Corn")
        self.assertEqual(assignment.crop_code, 1)
        self.assertAlmostEqual(assignment.crop_pct, 57.143, places=3)
        self.assertEqual(assignment.valid_agricultural_pixels, 70)
        self.assertFalse(assignment.review_required)

    def test_below_40_percent_requires_review(self):
        assignment = classify_histogram(
            {1: 39, 5: 34, 24: 27}, "cache", 2023, threshold=0.40
        )
        self.assertEqual(assignment.status, "below_threshold")
        self.assertTrue(assignment.review_required)

    def test_exact_40_percent_is_accepted(self):
        assignment = classify_histogram({5: 40, 1: 35, 24: 25}, "cache", 2023)
        self.assertEqual(assignment.crop_name, "Soybeans")
        self.assertEqual(assignment.crop_pct, 40.0)
        self.assertFalse(assignment.review_required)

    def test_double_crop_requires_explicit_mapping(self):
        assignment = classify_histogram({26: 90, 5: 10}, "croplandcros", 2024)
        self.assertIsNone(assignment.crop_name)
        self.assertEqual(assignment.status, "mapping_required")
        self.assertTrue(assignment.review_required)

    def test_empty_agricultural_histogram_never_invents_crop(self):
        assignment = classify_histogram({0: 100, 121: 50}, "local_cdl", 2024)
        self.assertIsNone(assignment.crop_name)
        self.assertEqual(assignment.status, "no_agricultural_pixels")
        self.assertTrue(assignment.review_required)

    def test_manual_override_preserves_observed_class_provenance(self):
        automatic = classify_histogram({26: 90, 5: 10}, "cache", 2024)
        reviewed = apply_manual_override(automatic, "Soybeans", 2024)
        self.assertEqual(reviewed.crop_name, "Soybeans")
        self.assertEqual(reviewed.crop_code, 26)
        self.assertEqual(reviewed.crop_source, "manual")
        self.assertTrue(reviewed.crop_overridden)
        self.assertFalse(reviewed.review_required)


class CropCacheTests(unittest.TestCase):
    def test_cache_key_is_stable_and_partitions_year_and_extent(self):
        first, _ = cache_key("https://example.test/ImageServer", 2024, (1, 2, 3, 4), 30, "12.1")
        second, _ = cache_key("https://example.test/ImageServer/", 2024, (1, 2, 3, 4), 30, "12.1")
        self.assertEqual(first, second)
        self.assertNotEqual(
            first,
            cache_key("https://example.test/ImageServer", 2023, (1, 2, 3, 4), 30, "12.1")[0],
        )
        self.assertNotEqual(
            first,
            cache_key("https://example.test/ImageServer", 2024, (1, 2, 4, 5), 30, "12.1")[0],
        )

    def test_cache_requires_matching_complete_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = CdlCache(temporary)
            raster, metadata, request = cache.paths("endpoint", 2024, (1, 2, 3, 4), 30, "1")
            raster.parent.mkdir(parents=True, exist_ok=True)
            raster.write_bytes(b"fake raster")
            self.assertIsNone(cache.get("endpoint", 2024, (1, 2, 3, 4), 30, "1"))
            cache.store_metadata(metadata, request)
            self.assertEqual(
                cache.get("endpoint", 2024, (1, 2, 3, 4), 30, "1"), raster
            )

    def test_clear_cache_removes_only_owned_cache_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owned = [root / "cdl_2025_example.tif", root / "cdl_2025_example.json"]
            unrelated = root / "keep-me.txt"
            for path in owned + [unrelated]:
                path.write_text("test", encoding="utf-8")
            self.assertEqual(cached_files(root), sorted(owned))
            self.assertEqual(clear_cached_files(root), sorted(owned))
            self.assertTrue(unrelated.is_file())
            self.assertFalse(any(path.exists() for path in owned))


class CroplandCrosAdapterTests(unittest.TestCase):
    def test_fetch_uses_cached_raster_without_export_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = CroplandCrosSource(temporary, endpoint="https://example.test/ImageServer")
            extent = (1.0, 2.0, 301.0, 302.0)
            raster, metadata, request = source.cache.paths(
                source.endpoint, 2024, extent, 30.0, "12.1"
            )
            raster.parent.mkdir(parents=True, exist_ok=True)
            raster.write_bytes(b"cached")
            source.cache.store_metadata(metadata, request)
            with patch.object(source, "service_info", return_value={"currentVersion": 12.1, "pixelSizeX": 30}):
                with patch.object(source, "available_years") as years:
                    result, source_name, details = source.fetch(2024, extent)
            self.assertEqual(result, raster)
            self.assertEqual(source_name, "cache")
            self.assertEqual(details["pixel_size"], 30.0)
            years.assert_not_called()

    def test_fetch_rejects_missing_year_before_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = CroplandCrosSource(temporary, endpoint="https://example.test/ImageServer")
            with patch.object(
                source,
                "service_info",
                return_value={"currentVersion": 12.1, "pixelSizeX": 30, "maxImageWidth": 4096, "maxImageHeight": 4096},
            ), patch.object(source, "available_years", return_value=[2023, 2024]):
                with self.assertRaisesRegex(ValueError, "year 2025 is unavailable"):
                    source.fetch(2025, (1, 2, 301, 302))


if __name__ == "__main__":
    unittest.main()
