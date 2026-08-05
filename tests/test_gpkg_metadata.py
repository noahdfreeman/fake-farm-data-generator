import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fake_farm_data_generator.core.gpkg_metadata import write_gpkg_run_metadata


class GeoPackageMetadataTests(unittest.TestCase):
    def test_writes_registered_attribute_table(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "output.gpkg"
            with closing(sqlite3.connect(path)) as connection:
                connection.execute(
                    """
                    CREATE TABLE gpkg_contents (
                        table_name TEXT PRIMARY KEY,
                        data_type TEXT NOT NULL,
                        identifier TEXT,
                        description TEXT DEFAULT '',
                        last_change DATETIME NOT NULL,
                        min_x DOUBLE,
                        min_y DOUBLE,
                        max_x DOUBLE,
                        max_y DOUBLE,
                        srs_id INTEGER
                    )
                    """
                )
                connection.commit()
            changed = write_gpkg_run_metadata(
                [path],
                {
                    "schema_version": 1,
                    "status": "running",
                    "fake_data": True,
                    "fake_warning": "FAKE DATA",
                    "generator": "Fake Farm Data Generator 0.16.0",
                    "run_id": "run-1",
                    "master_seed": 42,
                    "unit_system": "Imperial",
                },
            )
            self.assertEqual(changed, [path])
            with closing(sqlite3.connect(path)) as connection:
                values = dict(
                    connection.execute(
                        "SELECT metadata_key, metadata_value FROM ffdg_run_metadata"
                    )
                )
                registration = connection.execute(
                    "SELECT data_type FROM gpkg_contents WHERE table_name='ffdg_run_metadata'"
                ).fetchone()
            self.assertEqual(values["status"], "complete")
            self.assertEqual(values["fake_data"], "true")
            self.assertEqual(values["master_seed"], "42")
            self.assertEqual(registration, ("attributes",))


if __name__ == "__main__":
    unittest.main()
