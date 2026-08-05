import unittest

from tools.verify_release_version import metadata_version, normalize_tag, verify


class ReleaseVersionTests(unittest.TestCase):
    def test_metadata_version_and_tag_normalization(self):
        self.assertEqual(metadata_version(), "1.0.0")
        self.assertEqual(normalize_tag("v1.0.0"), "1.0.0")
        self.assertEqual(normalize_tag("1.0.0"), "1.0.0")

    def test_current_release_files_agree(self):
        self.assertEqual(verify("v1.0.0"), "1.0.0")

    def test_mismatched_tag_fails(self):
        with self.assertRaisesRegex(ValueError, "does not match metadata"):
            verify("v9.9.9")


if __name__ == "__main__":
    unittest.main()
