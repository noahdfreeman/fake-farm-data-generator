# SPDX-License-Identifier: GPL-3.0-or-later
"""Write portable run metadata into generated GeoPackages."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def metadata_values(manifest):
    """Return stable string values suitable for an attribute-only GPKG table."""

    keys = (
        "schema_version",
        "status",
        "fake_data",
        "fake_warning",
        "generator",
        "run_id",
        "created_at",
        "master_seed",
        "unit_system",
        "field_count",
    )
    values = {}
    for key in keys:
        if key not in manifest:
            continue
        value = manifest[key]
        values[key] = (
            json.dumps(value, separators=(",", ":"))
            if isinstance(value, (dict, list, bool))
            else str(value)
        )
    values["manifest_file"] = "run_manifest.json"
    return values


def write_gpkg_run_metadata(paths, manifest):
    """Create or replace `ffdg_run_metadata` in every supplied GeoPackage."""

    values = metadata_values({**manifest, "status": "complete"})
    changed = []
    last_change = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for raw_path in paths:
        path = Path(raw_path)
        if path.suffix.casefold() != ".gpkg" or not path.is_file():
            continue
        with closing(sqlite3.connect(path)) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ffdg_run_metadata (
                    metadata_key TEXT PRIMARY KEY NOT NULL,
                    metadata_value TEXT NOT NULL
                )
                """
            )
            connection.execute("DELETE FROM ffdg_run_metadata")
            connection.executemany(
                "INSERT INTO ffdg_run_metadata(metadata_key, metadata_value) VALUES (?, ?)",
                sorted(values.items()),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO gpkg_contents
                    (table_name, data_type, identifier, description, last_change, srs_id)
                VALUES
                    ('ffdg_run_metadata', 'attributes', 'ffdg_run_metadata',
                     'Fake Farm Data Generator run metadata', ?, NULL)
                """,
                (last_change,),
            )
            connection.commit()
        changed.append(path)
    return changed
