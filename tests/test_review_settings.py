import unittest

from fake_farm_data_generator.core.review_settings import (
    DEFAULT_REVIEW_MAX_FEATURES,
    normalize_review_max_features,
)


class ReviewSettingsTests(unittest.TestCase):
    def test_default_is_twenty_thousand(self):
        self.assertEqual(DEFAULT_REVIEW_MAX_FEATURES, 20_000)
        self.assertEqual(normalize_review_max_features("20000"), 20_000)

    def test_bounds_and_whole_numbers_are_enforced(self):
        for invalid in (99, 200_001, 100.5, True, "many"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalize_review_max_features(invalid)


if __name__ == "__main__":
    unittest.main()
