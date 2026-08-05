# SPDX-License-Identifier: GPL-3.0-or-later
"""Consolidate complete-run component GeoPackages into one package per year."""

from __future__ import annotations

from pathlib import Path


METADATA_LAYER = "ffdg_run_metadata"


def spatial_layer_names(path):
    """Return spatial OGR layer names, excluding the run-metadata attribute table."""

    from osgeo import ogr

    dataset = ogr.Open(str(path), 0)
    if dataset is None:
        raise RuntimeError(f"Could not open GeoPackage: {path}")
    names = []
    for index in range(dataset.GetLayerCount()):
        layer = dataset.GetLayerByIndex(index)
        if layer is None:
            continue
        name = layer.GetName()
        if name != METADATA_LAYER and layer.GetGeomType() != ogr.wkbNone:
            names.append(name)
    dataset = None
    return names


def _copy_field_definition(source_field, ogr):
    target_field = ogr.FieldDefn(source_field.GetNameRef(), source_field.GetType())
    target_field.SetSubType(source_field.GetSubType())
    target_field.SetWidth(source_field.GetWidth())
    target_field.SetPrecision(source_field.GetPrecision())
    return target_field


def _target_layer(destination, source_layer, ogr):
    name = source_layer.GetName()
    target = destination.GetLayerByName(name)
    source_definition = source_layer.GetLayerDefn()
    if target is None:
        target = destination.CreateLayer(
            name,
            source_layer.GetSpatialRef(),
            source_layer.GetGeomType(),
            options=["SPATIAL_INDEX=YES"],
        )
        if target is None:
            raise RuntimeError(f"Could not create consolidated layer: {name}")
        for index in range(source_definition.GetFieldCount()):
            if target.CreateField(
                _copy_field_definition(source_definition.GetFieldDefn(index), ogr)
            ) != 0:
                raise RuntimeError(f"Could not create field in consolidated layer {name}")
        return target

    target_definition = target.GetLayerDefn()
    source_fields = [
        (
            source_definition.GetFieldDefn(index).GetNameRef(),
            source_definition.GetFieldDefn(index).GetType(),
        )
        for index in range(source_definition.GetFieldCount())
    ]
    target_fields = [
        (
            target_definition.GetFieldDefn(index).GetNameRef(),
            target_definition.GetFieldDefn(index).GetType(),
        )
        for index in range(target_definition.GetFieldCount())
    ]
    if source_fields != target_fields:
        raise RuntimeError(f"Component schemas differ for consolidated layer {name}")
    return target


def _append_source_package(source_path, destination, ogr, feedback=None):
    source = ogr.Open(str(source_path), 0)
    if source is None:
        raise RuntimeError(f"Could not open component GeoPackage: {source_path}")
    copied = {}
    for layer_index in range(source.GetLayerCount()):
        source_layer = source.GetLayerByIndex(layer_index)
        if (
            source_layer is None
            or source_layer.GetName() == METADATA_LAYER
            or source_layer.GetGeomType() == ogr.wkbNone
        ):
            continue
        target_layer = _target_layer(destination, source_layer, ogr)
        target_definition = target_layer.GetLayerDefn()
        source_layer.ResetReading()
        count = 0
        if target_layer.StartTransaction() != 0:
            raise RuntimeError(
                f"Could not start transaction for {source_layer.GetName()}"
            )
        try:
            for source_feature in source_layer:
                if (
                    feedback is not None
                    and count % 1000 == 0
                    and feedback.isCanceled()
                ):
                    raise RuntimeError("Processing canceled during GeoPackage consolidation")
                target_feature = ogr.Feature(target_definition)
                # _target_layer verifies that source and destination schemas match.
                # Let OGR copy fields, null state, and geometry in compiled code instead
                # of performing a Python field-name lookup for every attribute.
                if target_feature.SetFrom(source_feature, 1) != 0:
                    raise RuntimeError(
                        f"Could not copy feature from {source_layer.GetName()}"
                    )
                if target_layer.CreateFeature(target_feature) != 0:
                    raise RuntimeError(
                        f"Could not append feature to {source_layer.GetName()}"
                    )
                target_feature = None
                count += 1
            if target_layer.CommitTransaction() != 0:
                raise RuntimeError(
                    f"Could not commit consolidated layer {source_layer.GetName()}"
                )
        except Exception:
            target_layer.RollbackTransaction()
            raise
        copied[source_layer.GetName()] = count
    source = None
    return copied


def _component_geopackages(root, manifest):
    result = []
    for value in manifest.get("outputs", []):
        relative = Path(str(value))
        path = root / relative
        if relative.suffix.casefold() != ".gpkg" or not path.is_file():
            continue
        if relative.name.startswith("fake_farm_data_"):
            continue
        result.append(relative)
    return result


def consolidate_complete_run_geopackages(run_folder, manifest, years, feedback=None):
    """Create yearly multi-layer packages and archive intermediate component packages."""

    from osgeo import ogr

    root = Path(run_folder)
    source_relatives = _component_geopackages(root, manifest)
    boundary_relative = next(
        (relative for relative in source_relatives if relative.name == "fake_field_boundaries.gpkg"),
        None,
    )
    yearly_sources = {int(year): [] for year in years}
    for relative in source_relatives:
        if relative == boundary_relative or not relative.parent.name.isdigit():
            continue
        year = int(relative.parent.name)
        if year in yearly_sources:
            yearly_sources[year].append(relative)

    driver = ogr.GetDriverByName("GPKG")
    if driver is None:
        raise RuntimeError("GDAL GeoPackage driver is unavailable")
    consolidated = []
    layer_counts = {}
    for year in sorted(yearly_sources):
        if feedback is not None and feedback.isCanceled():
            raise RuntimeError("Processing canceled during GeoPackage consolidation")
        year_folder = root / str(year)
        year_folder.mkdir(parents=True, exist_ok=True)
        destination_path = year_folder / f"fake_farm_data_{year}.gpkg"
        if destination_path.exists():
            raise RuntimeError(f"Consolidated GeoPackage already exists: {destination_path}")
        destination = driver.CreateDataSource(str(destination_path))
        if destination is None:
            raise RuntimeError(f"Could not create consolidated GeoPackage: {destination_path}")
        sources = ([boundary_relative] if boundary_relative is not None else []) + yearly_sources[year]
        per_year_counts = {}
        for relative in sources:
            if feedback is not None and feedback.isCanceled():
                raise RuntimeError("Processing canceled during GeoPackage consolidation")
            copied = _append_source_package(
                root / relative, destination, ogr, feedback
            )
            for layer_name, count in copied.items():
                per_year_counts[layer_name] = per_year_counts.get(layer_name, 0) + count
        destination = None
        if not per_year_counts:
            raise RuntimeError(f"No spatial layers were available for crop year {year}")
        consolidated.append(destination_path)
        layer_counts[str(year)] = per_year_counts
        if feedback is not None:
            feedback.pushInfo(
                f"Consolidated {len(per_year_counts)} layer(s) into {destination_path.name}"
            )

    # QGIS may retain read locks on child GeoPackages for the lifetime of the
    # Processing context, especially on Windows. Keep these intermediate files
    # in place for component provenance, but remove them from the public output
    # list so the yearly package is the canonical user-facing GeoPackage.
    source_map = {
        relative.as_posix(): relative.as_posix() for relative in source_relatives
    }
    for component in manifest.get("components", []):
        component["outputs"] = [
            source_map.get(Path(str(value)).as_posix(), Path(str(value)).as_posix())
            for value in component.get("outputs", [])
        ]
    manifest["outputs"] = [
        Path(str(value)).as_posix()
        for value in manifest.get("outputs", [])
        if Path(str(value)).as_posix() not in source_map
    ]
    consolidated_relatives = [path.relative_to(root).as_posix() for path in consolidated]
    manifest["outputs"].extend(consolidated_relatives)
    manifest["component_source_outputs"] = sorted(source_map.values())
    manifest["yearly_geopackages"] = {
        str(year): (Path(str(year)) / f"fake_farm_data_{year}.gpkg").as_posix()
        for year in sorted(yearly_sources)
    }
    manifest["yearly_geopackage_layer_counts"] = layer_counts
    return consolidated
