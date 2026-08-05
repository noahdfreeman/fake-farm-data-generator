import unittest

from tools.verify_release_version import (
    metadata_version,
    normalize_tag,
    requested_tag,
    verify,
)


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

    def test_github_branch_name_is_not_treated_as_release_tag(self):
        branch_environment = {
            "GITHUB_REF_TYPE": "branch",
            "GITHUB_REF_NAME": "agent/v1-public-release",
        }
        tag_environment = {
            "GITHUB_REF_TYPE": "tag",
            "GITHUB_REF_NAME": "v1.0.0",
        }
        self.assertEqual(requested_tag([], branch_environment), "")
        self.assertEqual(requested_tag([], tag_environment), "v1.0.0")
        self.assertEqual(requested_tag(["v2.0.0"], branch_environment), "v2.0.0")


if __name__ == "__main__":
    unittest.main()
