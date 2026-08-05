import re
import unittest
import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTests(unittest.TestCase):
    def test_v1_documentation_pages_exist(self):
        required = {
            "index.md",
            "installation.md",
            "complete-run.md",
            "individual-tools.md",
            "parameters.md",
            "schemas.md",
            "crop-sources.md",
            "outputs-and-review.md",
            "development-and-release.md",
        }
        actual = {path.name for path in (ROOT / "docs").glob("*.md")}
        self.assertTrue(required <= actual, sorted(required - actual))

    def test_local_documentation_links_resolve(self):
        pattern = re.compile(r"\[[^]]+\]\(([^)]+)\)")
        broken = []
        for page in (ROOT / "docs").glob("*.md"):
            for target in pattern.findall(page.read_text(encoding="utf-8")):
                clean = target.split("#", 1)[0].strip()
                if not clean or "://" in clean or clean.startswith("mailto:"):
                    continue
                if not (page.parent / clean).resolve().exists():
                    broken.append(f"{page.name}: {target}")
        self.assertEqual(broken, [])

    def test_release_workflows_cover_v1_gates(self):
        workflows = ROOT / ".github" / "workflows"
        required = {"ci.yml", "qgis-smoke.yml", "release.yml", "pages.yml"}
        self.assertTrue(required <= {path.name for path in workflows.glob("*.yml")})
        qgis = (workflows / "qgis-smoke.yml").read_text(encoding="utf-8")
        for version in ("3.34", "3.40", "3.44", "4.2"):
            self.assertIn(f'qgis: "{version}"', qgis)
            self.assertIn(f"qgis/qgis:{version}", qgis)
        self.assertIn("runs-on: macos-14", qgis)
        self.assertIn("brew install --cask qgis", qgis)
        self.assertIn("tools/run_qgis_smoke_macos.sh", qgis)
        linux_runner = ROOT / "tools" / "run_qgis_smoke_linux.sh"
        linux_text = linux_runner.read_text(encoding="utf-8")
        self.assertIn("QGIS_SMOKE_OK", linux_text)
        self.assertIn("PIPESTATUS[0]", linux_text)
        macos_runner = ROOT / "tools" / "run_qgis_smoke_macos.sh"
        self.assertTrue(macos_runner.is_file())
        macos_text = macos_runner.read_text(encoding="utf-8")
        self.assertIn("QGIS_PREFIX_PATH", macos_text)
        self.assertIn("Contents/Resources", macos_text)
        self.assertIn("Resources/Python.app/Contents/MacOS/Python", macos_text)
        self.assertIn("tests/qgis_smoke_test.py", macos_text)
        release = (workflows / "release.yml").read_text(encoding="utf-8")
        self.assertIn("tools/verify_release_version.py", release)
        self.assertIn("tools/validate_release_archive.py", release)
        self.assertIn("sha256sum", release)
        pages = (workflows / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("actions/upload-pages-artifact@v4", pages)
        self.assertIn("actions/deploy-pages@v4", pages)

    def test_issue_and_pull_request_templates_exist(self):
        github = ROOT / ".github"
        self.assertTrue((github / "ISSUE_TEMPLATE" / "bug_report.yml").is_file())
        self.assertTrue((github / "ISSUE_TEMPLATE" / "feature_request.yml").is_file())
        self.assertTrue((github / "pull_request_template.md").is_file())

    def test_release_tree_has_no_pending_algorithm_scaffolds(self):
        algorithms = ROOT / "fake_farm_data_generator" / "algorithms"
        self.assertFalse((algorithms / "pending.py").exists())
        demo_readme = (ROOT / "docs" / "demo" / "README.md").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("publishing placeholder", demo_readme.lower())
        provider = (
            ROOT / "fake_farm_data_generator" / "provider.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("pending", provider.lower())

    def test_public_fixtures_are_not_excluded_by_generated_data_rules(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("!tests/fixtures/*.geojson", ignore)
        self.assertIn("!docs/demo/sample_run/**/*.gpkg", ignore)
        self.assertIn("dist/", ignore)

    def test_public_demo_is_complete_and_labeled(self):
        demo = ROOT / "docs" / "demo"
        run = demo / "sample_run"
        manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
        recipe = json.loads((run / "run_recipe.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "complete")
        self.assertTrue(manifest["fake_data"])
        self.assertEqual(
            recipe["fake_warning"], "FAKE DATA - NOT FOR AGRONOMIC DECISIONS"
        )
        self.assertEqual(len(manifest["components"]), 6)
        self.assertTrue((run / "fake_farm_data_review.html").is_file())
        layers = (
            run / "fake_farm_data_review_data" / "layers.js"
        ).read_text(encoding="utf-8")
        for layer_prefix in (
            "fake_soil_tests_",
            "fake_soil_surface_",
            "fake_planting_center_",
            "fake_planting_rows_",
            "fake_applications_",
            "fake_yield_points_",
        ):
            self.assertIn(layer_prefix, layers)
        archive_path = demo / "fake-farm-data-demo.zip"
        self.assertTrue(archive_path.is_file())
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
        self.assertTrue(names)
        self.assertTrue(all(name.startswith("fake-farm-data-demo/") for name in names))
        self.assertFalse(any(".." in Path(name).parts for name in names))


if __name__ == "__main__":
    unittest.main()
